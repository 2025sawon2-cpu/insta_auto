"""Local-only CLI for the PC -> WireGuard -> Android publication path."""
import argparse
from dataclasses import asdict
import getpass
import importlib.metadata
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys

from .config import load_settings
from .mobile_device import AdbDevice, AndroidUI, DeviceConfig, DeviceRegistry, MobileError, device_name, phone_lock, run
from .mobile_reels import ReelsController, ReelJobs
from .post_preparation import PostPreparation


def pc_wireguard():
    """IPv4 addresses of this PC's WireGuard adapters (read-only)."""
    if os.name!='nt':
        return []
    script = ('[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); '
              'Get-NetAdapter | Where-Object InterfaceDescription -Like "*WireGuard*" | '
              'ForEach-Object { Get-NetIPAddress -InterfaceIndex $_.ifIndex -AddressFamily IPv4 } | '
              'Select-Object InterfaceAlias,IPAddress,PrefixLength | ConvertTo-Json -Compress')
    try:
        raw = run(['powershell.exe','-NoProfile','-Command',script]).decode('utf8').strip()
        value = json.loads(raw) if raw else []
    except Exception:
        return []
    return value if isinstance(value,list) else [value]


def reconfigure(saved, phone_ip, adb_port, vpn_network, adapters):
    """New device settings. Port-only changes keep the saved phone and its serial check;
    a given phone IP is a (re)registration, so connect stores that phone's serial again."""
    if not phone_ip:
        if not saved.phone_ip:
            raise MobileError('처음 설정에는 --phone-ip가 필요합니다.')
        return DeviceConfig(saved.phone_ip,adb_port,vpn_network or saved.vpn_network,saved.android_serial)
    if not vpn_network:
        ip = ipaddress.ip_address(phone_ip)
        networks = [ipaddress.ip_network(f"{a['IPAddress']}/{a['PrefixLength']}",strict=False) for a in adapters]
        matches = [str(n) for n in networks if ip in n]
        if not matches:
            raise MobileError('이 PC의 WireGuard 대역에 휴대폰 IP가 없습니다. --vpn-network로 대역을 지정하세요.')
        vpn_network = matches[0]
    return DeviceConfig(phone_ip,adb_port,vpn_network)


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
        result['wireguard_pc'] = pc_wireguard()
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
    registry = DeviceRegistry(settings.data_dir)
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument('--config',type=Path)
    selection.add_argument('--device',type=device_name,help='등록할 폰 이름 또는 사용할 기기. 기존 폰은 primary')
    commands = parser.add_subparsers(dest='command',required=True)
    commands.add_parser('doctor')
    commands.add_parser('devices')
    configure = commands.add_parser('configure')
    configure.add_argument('--phone-ip',help='생략하면 저장된 폰을 유지하고 포트만 바꾼다')
    configure.add_argument('--adb-port',type=int,required=True)
    configure.add_argument('--vpn-network',help='생략하면 이 PC의 WireGuard 대역에서 찾는다')
    pair = commands.add_parser('pair')
    pair.add_argument('--pairing-port',type=int,required=True)
    commands.add_parser('connect')
    prepare = commands.add_parser('prepare')
    prepare.add_argument('shortcode')
    prepare.add_argument('--account',required=True,help='이 설치에 등록한 게시용 Instagram 계정')
    for name in ('status','inspect','transfer','fill-caption','ready','reconcile','advance','cancel'):
        commands.add_parser(name).add_argument('job')
    op = commands.add_parser('open')
    op.add_argument('job');op.add_argument('--via',choices=['instagram','edits'],default='edits')
    binding = commands.add_parser('bind-littly')
    binding.add_argument('job');binding.add_argument('--receipt',type=Path,required=True)
    select = commands.add_parser('select-edits-video')
    select.add_argument('job'); select.add_argument('--screen-sha', required=True)
    cover_select = commands.add_parser('select-cover')
    cover_select.add_argument('job'); cover_select.add_argument('--screen-sha',required=True)
    audio = commands.add_parser('select-edits-audio')
    audio.add_argument('job'); audio.add_argument('--catalog-sha', required=True); audio.add_argument('--track-id', required=True)
    volume = commands.add_parser('record-edits-volume')
    volume.add_argument('job'); volume.add_argument('--percent',type=int,required=True); volume.add_argument('--screen-sha',required=True)
    identity = commands.add_parser('record-handoff-account')
    identity.add_argument('job'); identity.add_argument('--screen-label',required=True)
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
    jobs = ReelJobs(root) if hasattr(args,'job') or args.command=='prepare' else None
    bound_device = jobs.get(args.job)['package'].get('device_id','primary') if hasattr(args,'job') else None
    selected_device = args.device or bound_device or 'primary'
    if bound_device and args.device and bound_device != args.device:
        raise MobileError('이 작업에 지정된 휴대폰과 --device가 다릅니다.')
    if args.config and selected_device != 'primary':
        raise MobileError('이름으로 등록된 폰 작업에는 --config 대신 --device를 사용하세요.')
    config_path = args.config or registry.path(selected_device)
    def save_config(config):
        if args.config:
            config.save(config_path)
        else:
            registry.save(selected_device,config)
    lock_folder = registry.lock_folder(selected_device)
    if args.command=='devices':
        answer = {'devices':registry.devices(),'live_connection_checked':False}
    elif args.command=='doctor':
        answer = {'device_id':selected_device,**diagnostics(config_path)}
    elif args.command=='configure':
        adapters = [] if args.vpn_network or not args.phone_ip else pc_wireguard()
        config = reconfigure(DeviceConfig.load(config_path),args.phone_ip,args.adb_port,args.vpn_network,adapters)
        with phone_lock(lock_folder):
            save_config(config)
        answer = {'saved':True,'device_id':selected_device,'config_file':str(config_path),'endpoint':config.endpoint,
                  'vpn_network':config.vpn_network,'connected':False}
    else:
        if args.command=='prepare':
            DeviceConfig.load(config_path).validate()
            answer = jobs.prepare(PostPreparation(settings),args.shortcode,args.account,device_id=selected_device)
        elif args.command=='status':
            answer = jobs.get(args.job)
        elif args.command=='bind-littly':
            with phone_lock(lock_folder):
                answer = jobs.bind_littly(args.job,PostPreparation(settings),args.receipt)
        elif args.command=='cancel':
            with phone_lock(lock_folder):
                answer = jobs.cancel(args.job)
        else:
            config = DeviceConfig.load(config_path).validate()
            adb = AdbDevice(config)
            with phone_lock(lock_folder):
                if args.command=='pair':
                    # phone-pair.cmd pipes the code; getpass reads the console, not a pipe.
                    code = getpass.getpass('휴대폰 6자리 페어링 코드: ') if sys.stdin.isatty() else sys.stdin.readline().strip()
                    answer = adb.pair(args.pairing_port,code)
                elif args.command=='connect':
                    answer = adb.connect()
                    config.android_serial = answer['android_serial']
                    save_config(config)
                else:
                    # Verify the route and device identity again for every control session.
                    adb.connect()
                    if not config.android_serial:
                        raise MobileError('connect로 휴대폰 식별자를 먼저 저장하세요.')
                    ui = AndroidUI(config.endpoint)
                    jobs = jobs or ReelJobs(root)
                    controller = ReelsController(jobs,adb,ui,device_id=selected_device)
                    if args.command=='app':
                        ui.open_app('com.instagram.android' if args.name=='instagram' else 'com.instagram.basel')
                        screens = root/'device-screens' if selected_device=='primary' else root/'device-screens'/selected_device
                        answer = ui.capture(screens,'app-'+args.name)
                    elif args.command=='navigate':
                        answer = controller.navigate(args.job,args.node,args.screen_sha)
                    elif args.command=='open':
                        answer = controller.open(args.job,args.via)
                    elif args.command=='publish':
                        answer = controller.publish(args.job,args.approved_package_sha)
                    elif args.command=='fill-caption':
                        answer = controller.fill_caption(args.job)
                    elif args.command=='select-edits-video':
                        answer = controller.select_edits_video(args.job,args.screen_sha)
                    elif args.command=='select-cover':
                        answer = controller.select_cover(args.job,args.screen_sha)
                    elif args.command=='select-edits-audio':
                        answer = controller.select_edits_audio(args.job,args.track_id,args.catalog_sha)
                    elif args.command=='record-edits-volume':
                        answer = controller.record_edits_volume(args.job,args.percent,args.screen_sha)
                    elif args.command=='record-handoff-account':
                        answer = controller.record_handoff_account(args.job,args.screen_label)
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
