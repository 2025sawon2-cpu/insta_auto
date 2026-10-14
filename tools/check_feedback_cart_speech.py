"""Independently read actual final cart speech after fixing the missing audio."""
import json,subprocess
from pathlib import Path
import numpy as np
from faster_whisper import WhisperModel
from hotpost.config import load_settings
from hotpost.editing_adapter import _atomic_json

ROOT=Path('data/user-feedback-revisions-20261011/DeTJ6HbKCdF/final-v2').resolve()

def main():
    plan=json.loads((ROOT/'timeline.json').read_text('utf-8'))
    raw=subprocess.run(['ffmpeg','-v','error','-i',str(ROOT/'preview.mp4'),'-vn','-ac','1','-ar','16000',
        '-f','f32le','pipe:1'],capture_output=True,check=True).stdout
    samples=np.frombuffer(raw,dtype='<f4').copy()
    model=WhisperModel('small',device='cpu',compute_type='int8',
        download_root=str(load_settings().source_model_dir/'faster-whisper'))
    segments,_=model.transcribe(samples,language='ko',word_timestamps=True,beam_size=5,
        vad_filter=False,condition_on_previous_text=False)
    rows=[{'start':s.start,'end':s.end,'text':s.text,
        'words':[{'word':w.word,'start':w.start,'end':w.end} for w in s.words]} for s in segments]
    _atomic_json(ROOT/'actual-speech-asr.json',{'audio_seconds':len(samples)/16000,'segments':rows,
        'caption_cues':plan['cues'],'auditory_naturalness_reviewed':False})
    print([(r['start'],r['end'],r['text']) for r in rows],flush=True)

if __name__=='__main__':main()
