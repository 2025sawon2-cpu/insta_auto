"""Uniformly spaced full-source frames; inspect before approving clip windows."""
import argparse
import json
from pathlib import Path
import subprocess
from PIL import Image,ImageDraw
from tools.rework_tiktok_batch import ROOT


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--code');args=parser.parse_args()
    for ledger in ROOT.glob('*/discovery.json'):
        data=json.loads(ledger.read_text('utf-8'))
        if args.code and data['code']!=args.code:continue
        for row in data['candidates']:
            if not row.get('path'):continue
            path=Path(row['path']);folder=ledger.parent/'review'/path.stem;folder.mkdir(parents=True,exist_ok=True)
            contact=folder/'contact.jpg'
            if contact.exists():continue
            duration=row['video_meta']['duration']
            sheet=Image.new('RGB',(600,1512),'#222222');draw=ImageDraw.Draw(sheet)
            for i in range(12):
                second=min(duration-.1,duration*i/11)
                frame=folder/f'{i:02}.jpg'
                subprocess.run(['ffmpeg','-v','error','-y','-ss',str(second),'-i',str(path),'-frames:v','1','-vf','scale=200:356:force_original_aspect_ratio=decrease',str(frame)],check=True,capture_output=True,timeout=30)
                with Image.open(frame) as image:sheet.paste(image,((i%3)*200,(i//3)*378))
                draw.text(((i%3)*200+3,(i//3)*378+358),f'{second:.2f}s',fill='white')
            sheet.save(contact,quality=90)
            print(json.dumps({'code':data['code'],'url':row['url'],'contact':str(contact)},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
