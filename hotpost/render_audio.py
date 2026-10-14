"""Verify decoded render speech against the exact processed narration clock."""
from pathlib import Path
import subprocess
import numpy as np
from scipy.signal import correlate

RATE=8000

def decode(path):
    raw=subprocess.run(['ffmpeg','-v','error','-i',str(path),'-vn','-ac','1','-ar',str(RATE),
        '-f','f32le','pipe:1'],capture_output=True,check=True,timeout=120).stdout
    return np.frombuffer(raw,dtype='<f4')

def compare(render,voice,rate=RATE):
    issues=[];anchors=[]
    difference=(len(render)-len(voice))/rate
    if abs(difference)>.12:issues.append('출력 오디오의 실제 샘플 길이가 승인 음성과 다릅니다.')
    for second in np.arange(2.5,len(voice)/rate-1,2.5):
        at=round(second*rate);chunk=voice[at:at+rate]
        if len(chunk)<rate or np.sqrt(np.mean(chunk**2))<.002:continue
        lo=max(0,at-rate);hi=min(len(render),at+2*rate)
        if hi-lo<len(chunk):continue
        index=int(np.argmax(correlate(render[lo:hi],chunk,mode='valid',method='fft')))+lo
        match=render[index:index+len(chunk)]
        similarity=float(np.corrcoef(chunk,match)[0,1]) if np.std(match)>0 else 0
        offset=(index-at)/rate
        anchors.append({'voice_time':float(second),'render_time':index/rate,
                        'offset_seconds':offset,'correlation':round(similarity,5)})
        if similarity<.8 or abs(offset)>.15:
            issues.append(f'{second:g}초 음성이 실제 출력에서 일치하지 않거나 시간 이동했습니다.')
    if not anchors:issues.append('출력 음성의 시간 일치를 확인할 발화 근거가 없습니다.')
    return {'passed':not issues,'issues':issues,'duration_delta_seconds':round(difference,5),
            'anchors':anchors,'method':'decoded-sample-count-and-waveform-time-correlation-v1',
            'auditory_naturalness_reviewed':False}

def audit(video,voice):return compare(decode(Path(video)),decode(Path(voice)))
