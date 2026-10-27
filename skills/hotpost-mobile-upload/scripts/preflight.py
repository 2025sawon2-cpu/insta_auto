"""Read existing upload setup and durable jobs. No browser, phone, or effect dispatch."""
import argparse
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys


def rows(path, table, query, parameters=()):
    if not path.is_file():
        return []
    with closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(table,)).fetchone():
            return []
        return [dict(row) for row in db.execute(query,parameters)]


def inspect(repo, shortcode=None):
    repo=Path(repo).resolve()
    if not all((repo/name).is_file() for name in ('hotpost/mobile_reels_cli.py','AGENTS.md')):
        raise ValueError('실제 insta_auto 저장소를 --repo로 지정하세요.')
    sys.path.insert(0,str(repo))
    from hotpost.config import load_settings
    from hotpost.installation_settings import read
    data=Path(load_settings(create_dirs=False).data_dir).resolve()
    setup=read(data)
    devices=[]
    paths=[('primary',data/'.mobile-device.json')]
    paths.extend((path.stem,path) for path in sorted((data/'mobile-devices').glob('*.json')))
    for device,path in paths:
        if not path.is_file():
            continue
        value=json.loads(path.read_text('utf8'))
        devices.append({'device_id':device,'configured':bool(value.get('phone_ip') and value.get('adb_port')),
                        'identity_saved':bool(value.get('android_serial')),'live_connection_checked':False})
    jobs=[]
    for row in rows(data/'mobile-reels/jobs.sqlite3','jobs','SELECT id,phase,value FROM jobs'):
        value=json.loads(row['value']);package=value.get('package',{})
        if shortcode and package.get('shortcode')!=shortcode:
            continue
        jobs.append({'job':row['id'],'phase':row['phase'],'shortcode':package.get('shortcode'),
                     'account':package.get('account'),'device_id':package.get('device_id','primary'),
                     'share_attempted':bool(value.get('share_attempted_at')),
                     'must_not_resubmit':row['phase'] in ('submitting','unknown','submitted'),
                     'upstream_hold':bool(value.get('upstream_hold')),
                     'littly_post_connected':bool(value.get('littly_post_connected')),
                     'pinned_comment_status':(value.get('pinned_comment_publication') or {}).get('status','not_verified'),
                     'pinned_comment_verified':(value.get('pinned_comment_publication') or {}).get('pin_verified') is True,
                     'delivery_verified':value.get('delivery_verified') is True})
    slots=rows(data/'monetization/state.sqlite3','next_post_slots',
               'SELECT account,task_id,status FROM next_post_slots')
    return {'repo':str(repo),'data_dir':str(data),'read_only':True,
            'installation':setup,
            'installation_saved':read_configuration_exists(data),
            'devices':devices,'jobs':jobs,'next_post_slots':slots,
            'live_checks_required':['existing Chrome profile and Instagram discovery account',
                                    'Littly connected publication account',
                                    'Coupang Influencer own store and tag',
                                    'phone route/serial and Instagram/Edits account before upload']}


def read_configuration_exists(data):
    return bool(rows(data/'monetization/state.sqlite3','configuration',
                     "SELECT name FROM configuration WHERE name='installation'"))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',required=True,type=Path)
    parser.add_argument('--shortcode')
    args=parser.parse_args()
    try:
        result=inspect(args.repo,args.shortcode)
    except (ValueError,OSError,sqlite3.Error,ImportError) as exc:
        print(json.dumps({'read_only':True,'error':str(exc)},ensure_ascii=False))
        return 1
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':
    raise SystemExit(main())
