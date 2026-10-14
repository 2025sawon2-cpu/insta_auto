from pathlib import Path
from types import SimpleNamespace
from hotpost import source_finder
from hotpost.source_queries import product_query_plan


def test_bounded_review_reserves_full_uniform_sequence_and_samples_cuts_across_duration(tmp_path,monkeypatch):
    calls=[]
    monkeypatch.setattr(source_finder.shutil,'which',lambda tool:tool)
    def run(command,**kwargs):
        calls.append(command)
        if command[0]=='ffprobe':return SimpleNamespace(stdout='24',returncode=0)
        path=Path(command[-1])
        if '%03d' in str(path):
            for index in range(1,int(command[command.index('-frames:v')+1])+1):
                Path(str(path).replace('%03d',f'{index:03d}')).touch()
        else:path.touch()
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(source_finder,'_run',run)
    monkeypatch.setattr(source_finder,'dhash',lambda p:(2**64-1)<<int(p.stem.split('_')[-1]) if '_scene_' not in p.name else (2**64-1)<<20)
    frames=source_finder.extract_frames(Path('reference.mp4'),tmp_path,max_frames=6)
    assert [p.name for p in frames[:4]]==[f'frame_{i:03d}.jpg' for i in range(1,5)]
    assert 'fps=1/6.000000' in calls[1][calls[1].index('-vf')+1]
    assert [float(c[c.index('-ss')+1]) for c in calls if '-ss' in c]==[0,12]


def test_known_photo_magnet_caption_does_not_fall_back_to_acrylic_frame_catalog():
    plan=product_query_plan('사진을 냉장고 자석으로 만들어요',['clear acrylic photo frame','透明相框'],[],{},[])
    assert plan['products'][0]['en']=='DIY photo fridge magnets'
    assert not any('acrylic' in q['query'] for q in plan['query_details'])
