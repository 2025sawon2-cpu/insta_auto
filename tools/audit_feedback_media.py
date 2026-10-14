"""Read actual render audio and pixels; retain original seven unchanged."""
import json,subprocess
from pathlib import Path
import numpy as np
from faster_whisper import WhisperModel
from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json

ROOT=Path('data/user-feedback-20261011-v1').resolve()

def main():
    model=WhisperModel('small',device='cpu',compute_type='int8',
        download_root=str(load_settings().source_model_dir/'faster-whisper'))
    for code in ('DeTJ6HbKCdF','DeJ7hD6zsnR'):
        data=json.loads((ROOT/(code+'-baseline.json')).read_text('utf-8'))
        for kind,path in [('render',data['edit']['export_path']),('processed_voice',data['plan']['voice']['path'])]:
            out=ROOT/(code+'-'+kind+'-asr.json')
            if out.exists():continue
            raw=subprocess.run(['ffmpeg','-v','error','-i',path,'-vn','-ac','1','-ar','16000',
                '-f','f32le','pipe:1'],check=True,capture_output=True).stdout
            samples=np.frombuffer(raw,dtype='<f4').copy()
            segments,info=model.transcribe(samples,language='ko',word_timestamps=True,
                beam_size=5,vad_filter=False,condition_on_previous_text=False)
            value=[{'start':s.start,'end':s.end,'text':s.text,
                'words':[{'word':w.word,'start':w.start,'end':w.end,'probability':w.probability} for w in s.words]} for s in segments]
            _atomic_json(out,{'audio_seconds':len(samples)/16000,'model':'small-cpu-int8','segments':value})
            print(code,kind,[(s['start'],s['end'],s['text']) for s in value],flush=True)
    code='DeTaESASnr_';data=json.loads((ROOT/(code+'-baseline.json')).read_text('utf-8'))
    subprocess.run(['ffmpeg','-v','error','-y','-i',data['edit']['export_path'],'-vf',
        'fps=2,scale=360:640,tile=6x7','-frames:v','1',str(ROOT/'mirror-dense-overview.jpg')],check=True,capture_output=True)

if __name__=='__main__':main()
