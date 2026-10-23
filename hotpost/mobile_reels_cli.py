"""Local-only CLI for the PC -> WireGuard -> Android publication path."""
import argparse
from dataclasses import asdict
import getpass
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess

from .config import load_settings
from .mobile_device import AdbDevice, AndroidUI, DeviceConfig, MobileError, phone_lock, run
from .mobile_reels import ReelsController, ReelJobs
from .post_preparation import PostPreparation


def diagnostics(config_path):
    result = {'config_file':str(config_path),'connected':False,'phone_inspected':False,
              'local_only':True,'required':[]}
    try:
        from adbutils import adb_path
        result['adb_path'] = adb_path()
        result['adb_version'] = run([adb_path(),'version']).decode('utf8','replace').splitlines()[0]
        result['uiautomator2_version'] = importlib.metadata.version('uiautomator2')
    except (ImportError, OSError, subprocess.SubprocessError):
        result['required'].append('requirements-mobile.txt의 PC 도구 설치')
    if os.name=='nt':
        script = ('[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); '
                  'Get-NetAdapter | Where-Object InterfaceDescription -Like "*WireGuard*" | '
                  'ForEach-Object { Get-NetIPAddress -InterfaceIndex $_.ifIndex -AddressFamily IPv4 } | '
                  'Select-Object InterfaceAlias,IPAddress,PrefixLength | ConvertTo-Json -Compress')
        try:
            raw = run(['powershell.exe','-NoProfile','-Command',script]).decode('utf8').strip()
            result['wireguard_pc'] = json.loads(raw) if raw else []
        except Exception:
            result['wireguard_pc'] = []
    config = DeviceConfig.load(config_path)
    try:
        config.validate()
        result['configured_endpoint'] = config.endpoint
        result['status'] = 'configured_not_connected'
    except MobileError:
        result['status'] = 'needs_phone_details'
        result['required'] += ['휴대폰 WireGuard IP','무선 디버깅 ADB 연결 포트',
                               '최초 연결이면 페어링 포트 및 폰에서 페어링 승인']
    return result


def main():
    settings = load_settings()
    root = settings.data_dir/'mobile-reels'
    config_default = settings.data_dir/'.mobile-device.json'
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=config_default)
    commands = parser.add_subparsers(dest='command',required=True)
    commands.add_parser('doctor')
    configure = commands.add_parser('configure')
    configure.add_argument('--phone-ip',required=True)
    configure.add_argument('--adb-port',type=int,required=True)
    configure.add_argument('--vpn-network',default='10.9.0.0/24')
    pair = commands.add_parser('pair')
    pair.add_argument('--pairing-port',type=int,required=True)
    commands.add_parser('connect')
    prepare = commands.add_parser('prepare')
    prepare.add_argument('shortcode')
    prepare.add_argument('--account',required=True,choices=['mr.salrim','__ariddaum__'])
    for name in ('status','inspect','transfer','fill-caption','ready','reconcile','advance','cancel'):
        commands.add_parser(name).add_argument('job')
    op = commands.add_parser('open')
    op.add_argument('job');op.add_argument('--via',choices=['instagram','edits'],default='instagram')
    app = commands.add_parser('app')
    app.add_argument('name',choices=['instagram','edits'])
    tap = commands.add_parser('navigate')
    tap.add_argument('job');tap.add_argument('--node',type=int,required=True);tap.add_argument('--screen-sha',required=True)
    publish = commands.add_parser('publish')
    publish.add_argument('job');publish.add_argument('--approved-package-sha',required=True)
    review = commands.add_parser('review-cover')
    review.add_argument('job');review.add_argument('--screen-sha',required=True);review.add_argument('--cover-sha',required=True)
    result = commands.add_parser('confirm-result')
    result.add_argument('job');result.add_argument('--post-url',required=True);result.add_argument('--screen-sha',required=True)
    args = parser.parse_args()
    if args.command=='doctor':
        answer = diagnostics(args.config)
    elif args.command=='configure':
        config = DeviceConfig(args.phone_ip,args.adb_port,args.vpn_network)
        config.save(args.config)
        answer = {'saved':True,'config_file':str(args.config),'connected':False}
    else:
        jobs = ReelJobs(root)
        if args.command=='prepare':
            answer = jobs.prepare(PostPreparation(settings),args.shortcode,args.account)
        elif args.command=='status':
            answer = jobs.get(args.job)
        elif args.command=='cancel':
            with phone_lock(root):
                answer = jobs.cancel(args.job)
        else:
            config = DeviceConfig.load(args.config).validate()
            adb = AdbDevice(config)
            with phone_lock(root):
                if args.command=='pair':
                    answer = adb.pair(args.pairing_port,getpass.getpass('휴대폰 6자리 페어링 코드: '))
                elif args.command=='connect':
                    answer = adb.connect()
                    config.android_serial = answer['android_serial']
                    config.save(args.config)
                else:
                    # Verify the route and device identity again for every control session.
                    adb.connect()
                    if not config.android_serial:
                        raise MobileError('connect로 휴대폰 식별자를 먼저 저장하세요.')
                    ui = AndroidUI(config.endpoint)
                    controller = ReelsController(jobs,adb,ui)
                    if args.command=='app':
                        ui.open_app('com.instagram.android' if args.name=='instagram' else 'com.instagram.basel')
                        answer = ui.capture(root/'device-screens','app-'+args.name)
                    elif args.command=='navigate':
                        answer = controller.navigate(args.job,args.node,args.screen_sha)
                    elif args.command=='open':
                        answer = controller.open(args.job,args.via)
                    elif args.command=='publish':
                        answer = controller.publish(args.job,args.approved_package_sha)
                    elif args.command=='fill-caption':
                        answer = controller.fill_caption(args.job)
                    elif args.command=='review-cover':
                        answer = controller.review_cover(args.job,args.screen_sha,args.cover_sha)
                    elif args.command=='confirm-result':
                        answer = controller.confirm_result(args.job,args.post_url,args.screen_sha)
                    else:
                        answer = getattr(controller,args.command)(args.job)
                    # XML is saved privately on disk; keep command output compact.
                    if isinstance(answer,dict):
                        answer = {k:v for k,v in answer.items() if k!='xml'}
    print(json.dumps(answer,ensure_ascii=False,indent=2))


if __name__=='__main__':
    try:
        main()
    except (ValueError,OSError,subprocess.SubprocessError) as error:
        print(json.dumps({'error':str(error)},ensure_ascii=False))
        raise SystemExit(1)
