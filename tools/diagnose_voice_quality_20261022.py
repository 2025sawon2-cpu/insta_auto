"""Read-only diagnosis of existing audio; no synthesis or production mutations."""
import hashlib
import json
import sqlite3
import subprocess
import wave
from pathlib import Path
import numpy as np
from scipy.signal import correlate, correlation_lags
from audit_feedback_voice_20261016 import measurements

ROOT = Path(__file__).resolve().parents[1]
VB = ROOT.parent/'VoiceBench'
OUT = ROOT/'data/voice-quality-diagnosis-20261022'
JOB = ROOT/'data/studio/work-e482cae03cc64e96/job-f0e7d10756ff470e'

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def decode(p, rate=48000):
    r=subprocess.run(['ffmpeg','-v','error','-i',str(p),'-ac','1','-ar',str(rate),'-f','f32le','pipe:1'],check=True,capture_output=True)
    return np.frombuffer(r.stdout,dtype='<f4').astype(float)
def pcm(p):
    with wave.open(str(p),'rb') as w:
        assert w.getsampwidth()==2 and w.getnchannels()==1
        return np.frombuffer(w.readframes(w.getnframes()),dtype='<i2'),w.getframerate()
def metrics(x, rate):
    return dict(duration=len(x)/rate,peak=float(np.max(np.abs(x))),rms=float(np.sqrt(np.mean(x*x))),clipping_fraction=float(np.mean(np.abs(x)>=.999)),dc=float(np.mean(x)))
def difference(a,b):
    n=min(len(a),len(b));a=a[:n];b=b[:n]
    gain=float(np.dot(a,b)/np.dot(a,a));res=b-a*gain
    return dict(samples=n,gain=gain,corr=float(np.corrcoef(a,b)[0,1]),residual_snr_db=float(10*np.log10(np.sum((a*gain)**2)/max(1e-30,np.sum(res**2)))),max_error=float(np.max(np.abs(res))))

def main():
    OUT.mkdir(exist_ok=True)
    plan=json.loads((JOB/'timeline.json').read_text('utf-8'))
    cuts=plan['pause_processing']
    if not isinstance(cuts,dict) or 'keeps' not in cuts:
        cuts=json.loads(next(JOB.glob('narration-*.cut-map.json')).read_text('utf-8'))
    original=Path(plan['voice_source']['path']);edited=Path(plan['voice']['path'])
    op,rate=pcm(original);ep,_=pcm(edited)
    expected=np.concatenate([op[lo:hi] for lo,hi in cuts['keeps']])
    cut_audit=[];removed_before=0
    for c in cuts['cuts']:
        lo,hi=c['start_sample'],c['end_sample'];seg=op[lo:hi].astype(float)/32768
        join=lo-removed_before;removed_before+=hi-lo
        cut_audit.append({**c,'removed_rms_dbfs':float(20*np.log10(np.sqrt(np.mean(seg**2))+1e-20)),
            'removed_peak_dbfs':float(20*np.log10(np.max(np.abs(seg))+1e-20)),
            'output_join_seconds':join/rate,'join_step_dbfs':float(20*np.log10(abs(float(op[hi])-float(op[lo-1]))/32768+1e-20))})
    with sqlite3.connect((VB/'data/voicebench.sqlite3').as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row;records=[]
        active=db.execute("SELECT count(*) FROM studio_requests WHERE status in ('queued','running')").fetchone()[0]
        for request in (168,230,231,235,236,237,268):
            rows=db.execute('SELECT q.*,r.manifest_json,r.metrics_json FROM studio_requests q JOIN studio_segments s ON s.request_id=q.id JOIN runs r ON r.job_id=s.job_id WHERE q.id=?',(request,)).fetchall()
            if not rows:continue
            rr=dict(rows[0]);m=json.loads(rr['manifest_json']);mt=json.loads(rr['metrics_json']);path=Path(rr['output_path'])
            q=mt.get('quality_control',{});performance=mt.get('engine_performance',{})
            config={k:m.get(k) for k in ('engine','continuity','seed','selected_seed','synthesis','reference_sha256')}
            records.append(dict(request_id=request,audio_path=str(path),sha256=sha(path),segments=len(rows),effective_config=config,
                actual_adapter=m.get('adapter'),proxy_measurements=measurements(path,rr['original_text']),
                quality_control=q,engine_performance=performance,waveform=metrics(decode(path),48000)))
        current=json.loads(db.execute('SELECT r.manifest_json FROM studio_segments s JOIN runs r ON r.job_id=s.job_id WHERE s.request_id=268').fetchone()[0])
    baseline=records[0]['effective_config']
    baseworker=records[0]['actual_adapter']['worker']
    for r in records:
        r['same_manifest_configuration_as_168']=r['effective_config']==baseline
        w=r['actual_adapter']['worker']
        r['same_effective_worker_config_as_168']=all(w.get(k)==baseworker.get(k) for k in ('backend','dac_device','generation','model','model_path','quantization','runtime_version','sample_rate','speaker_encoder'))
    m={}
    arrays={}
    for name,path in [('original',original),('edited',edited),('effects',Path(plan['sfx_path'])),('mixed',JOB/'narration-mix.wav'),('final',JOB/'preview.mp4')]:
        arrays[name]=decode(path);m[name]={'path':str(path),'sha256':sha(path),**metrics(arrays[name],48000)}
    spoken=arrays['edited'];fx=arrays['effects'];mix=arrays['mixed'];final=arrays['final']
    predicted=spoken.astype('<f4').copy();n=min(len(predicted),len(fx));predicted[:n]+=fx[:n].astype('<f4')
    expectedmix=(np.clip(predicted,-1,1)*32767).astype('<i2')
    actualmix,_=pcm(JOB/'narration-mix.wav')
    corr=correlate(final,mix,mode='full',method='fft');lags=correlation_lags(len(final),len(mix));lag=int(lags[np.argmax(corr)])
    aa=mix[max(0,-lag):];bb=final[max(0,lag):]
    residual=mix[:len(spoken)]-spoken[:len(mix)]
    frame=4800;n=min(len(spoken),len(residual))//frame
    vr=np.sqrt(np.mean(spoken[:n*frame].reshape(n,frame)**2,axis=1));fr=np.sqrt(np.mean(residual[:n*frame].reshape(n,frame)**2,axis=1))
    noisy=[{'start':i*.1,'end':(i+1)*.1,'voice_rms':float(vr[i]),'effects_rms':float(fr[i]),'fx_to_voice_db':float(20*np.log10((fr[i]+1e-12)/(vr[i]+1e-12)))} for i in range(n) if fr[i]>.001 and fr[i]>vr[i]*.5]
    probe=json.loads(subprocess.run(['ffprobe','-v','error','-select_streams','a:0','-show_streams','-of','json',str(JOB/'preview.mp4')],capture_output=True,check=True).stdout)
    engine=VB/f"data/artifacts/outputs/project-3/prompt-{current['job_id']}/job-{current['job_id']}-zonos2-q8-experimental-seed-13.wav"
    engine_match=None
    if engine.exists():
        ee,_=pcm(engine);engine_match={'path':str(engine),'sha256':sha(engine),'samples':len(ee),'pcm_equals_hotpost_original':bool(np.array_equal(ee,op))}
    report=dict(active_requests=active,new_synthesis=0,auditory_review_performed=False,records=records,stages=m,
        edited_equals_keep_concatenation=bool(np.array_equal(expected,ep)),cuts=cut_audit,
        voicebench_request_equals_hotpost_original=sha(VB/'data/artifacts/studio/request-268.wav')==sha(original),engine_original=engine_match,
        mixed_equals_expected_pcm=bool(np.array_equal(expectedmix,actualmix)),effects_policy=plan.get('sound_effects'),
        mixed_vs_narration=difference(spoken,mix),mixed_vs_narration_plus_fx=difference(predicted,mix),
        effect_to_voice_power_db=float(10*np.log10(np.sum(residual**2)/np.sum(spoken[:len(residual)]**2))),
        effects_at_least_half_voice_rms_100ms=noisy,final_audio_stream=probe['streams'],final_alignment_lag_samples=lag,final_vs_mix=difference(aa,bb))
    (OUT/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    summary={k:v for k,v in report.items() if k not in ('records','effects_policy','final_audio_stream','effects_at_least_half_voice_rms_100ms')}
    summary['requests']=[{k:r[k] for k in ('request_id','same_manifest_configuration_as_168','segments','waveform')} for r in records]
    summary['effects_policy']=report['effects_policy'];summary['loud_fx_windows']=noisy
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
