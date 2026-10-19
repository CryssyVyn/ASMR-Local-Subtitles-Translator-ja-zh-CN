"""Offline playback captions. Audio stays in RAM; only loopback HTTP is allowed."""
from pathlib import Path
import os
for key in ('HF_HUB_OFFLINE', 'TRANSFORMERS_OFFLINE', 'HF_HUB_DISABLE_TELEMETRY'):
    os.environ[key] = '1'
os.environ['HF_HUB_DISABLE_IMPLICIT_TOKEN'] = '1'
import ctypes
import ipaddress
import json
import math
import queue
import re
import socket
import secrets
import subprocess
import threading
import time
from collections import deque
import urllib.request

BASE = Path(__file__).resolve().parent

def install_network_guard():
    """Enforce local-only sockets in this Python process, including dependencies."""
    def audit(event, args):
        if event not in ('socket.connect', 'socket.bind', 'socket.getaddrinfo'):
            return
        address = args[1] if event != 'socket.getaddrinfo' else (args[0], args[1])
        if not isinstance(address, tuple) or not address:
            raise PermissionError('运行期间仅允许本机网络连接')
        host = address[0]
        if host in ('localhost', b'localhost'):
            return
        try:
            if ipaddress.ip_address(host).is_loopback:
                return
        except ValueError:
            pass
        raise PermissionError('已阻止运行期间的外部网络访问')
    import sys
    sys.addaudithook(audit)

import numpy as np
from scipy.signal import resample_poly
import pyaudiowpatch as pyaudio
from vendor.whispering_tiger.transcription_queue import RouteTranscriptionQueue
from asmr_chinese_plugin import LocalASMRClient

DEFAULTS = {
    'device_name': '', 'sensitivity': '标准', 'pause': 0.35, 'max_phrase': 3.0, 'fast_asr': True,
    'scene': '', 'glossary': json.loads((BASE/'词库_保守版_ja_zh.json').read_text(encoding='utf-8-sig')),
    'context': True, 'font_size': 22, 'topmost': True,
    'ja_font_size': 14, 'overlay_only_translation': True,
    'overlay_show_status': False, 'overlay_streaming': True,
    'overlay_transparent_bg': True, 'overlay_zh_color': '#f5f3ed', 'overlay_ja_color': '#dedcd6',
    'overlay_font_weight': 'normal', 'overlay_outline_width': 1, 'overlay_shadow': True,
    'translation_backend': 'auto', 'cpu_llm_threads': 8,
}

def load_config():
    result = dict(DEFAULTS)
    path = BASE / '作品设置.json'
    if path.exists():
        data = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            result.update({k:v for k,v in data.items() if k in result})
    return result

def enumerate_devices():
    audio = pyaudio.PyAudio()
    try:
        devices = [dict(x) for x in audio.get_loopback_device_info_generator()]
        try:
            default = audio.get_default_wasapi_loopback()['name']
        except OSError:
            default = ''
        return devices, default
    finally:
        audio.terminate()

def resolve_loopback_device(audio, selected):
    """Resolve names in the same PortAudio session that will open the stream."""
    for device in audio.get_loopback_device_info_generator():
        if device['name'] == selected['name']:
            return dict(device)
    raise ValueError('所选播放设备已断开或名称已改变。请点击“刷新”，重新选择实际出声的耳机或扬声器。')

def capture_error_message(exc, device):
    code = getattr(exc, 'errno', None)
    if code is None and exc.args and isinstance(exc.args[0], int):
        code = exc.args[0]
    if code == pyaudio.paInvalidDevice:
        return (f'无法打开“{device.get("name", "所选播放设备")}”（错误 -9996）。'
                '请确认该设备已连接且能播放声音，点击“刷新”，选择实际出声的耳机或扬声器后重试。')
    return str(exc)

def mono_resample(audio, rate):
    audio = np.asarray(audio, dtype=np.float32)
    if audio.ndim == 2:
        # Keep speech that moves between ears. Fall back only if averaging cancels it.
        energies = np.mean(np.square(audio), axis=0)
        mixed = np.mean(audio, axis=1)
        if float(np.mean(np.square(mixed))) < float(np.max(energies))*0.12:
            audio = audio[:, int(np.argmax(energies))]
        else:
            audio = mixed
    if rate != 16000:
        gcd = math.gcd(int(rate), 16000)
        audio = resample_poly(audio, 16000//gcd, int(rate)//gcd)
    return np.ascontiguousarray(audio, dtype=np.float32)

def non_speech_reason(waveform):
    """Conservatively reject silence and almost-pure electronic tones."""
    wave=np.asarray(waveform,dtype=np.float32)
    if not wave.size or float(np.max(np.abs(wave))) < 0.0002:
        return 'silence'
    if len(wave)<4096:
        return ''
    window=np.hanning(4096)
    starts=np.linspace(0,len(wave)-4096,min(5,max(1,len(wave)//4096)),dtype=int)
    tone_count=0
    valid_count=0
    for offset in starts:
        part=wave[offset:offset+4096]
        if float(np.max(np.abs(part)))<0.0002:
            continue
        spectrum=np.abs(np.fft.rfft(part*window))**2
        total=float(np.sum(spectrum[1:]))
        if total<=1e-10:
            continue
        valid_count+=1
        peak=int(np.argmax(spectrum[1:]))+1
        narrow=float(np.sum(spectrum[max(1,peak-2):peak+3]))/total
        if narrow>0.97:
            tone_count+=1
    return 'tone' if valid_count and tone_count==valid_count else ''


_SOUND_SEPARATORS = r'[\s、,，・。.…!?！？]*'
_REPEATED_TEXT = re.compile(
    r'(?P<unit>[^\s、,，・。.…!?！？]{1,8}?)(?:' + _SOUND_SEPARATORS + r'(?P=unit)){5,}')
_SOUND_UNIT = re.compile(
    r'(?:[ふフはハへヘひヒほホあアうウえエおオんンっッぁァぃィぅゥぇェぉォー〜～呵哈嘿嘻呼嗯啊]|くす|クス)+')
_SOUND_PUNCTUATION = re.compile(r'[\s、,，・。.…!?！？「」『』（）()\[\]【】〜～]+')


def normalize_asr_repetition(text):
    """Skip extreme sound-only loops; shorten loops embedded in real speech.

    Short laughter and repeated words are deliberately left alone. This is a
    text heuristic, not a determination of what was actually heard in the audio.
    """
    changed = False
    def shorten(match):
        nonlocal changed
        unit = match.group('unit')
        compact = _SOUND_PUNCTUATION.sub('', match.group(0))
        if len(compact) < 12 or not _SOUND_UNIT.fullmatch(unit):
            return match.group(0)
        changed = True
        return unit * 3 + '…'
    cleaned = _REPEATED_TEXT.sub(shorten, text)
    if changed:
        compact = _SOUND_PUNCTUATION.sub('', cleaned)
        if not compact or _SOUND_UNIT.fullmatch(compact):
            return '', True
    return cleaned, changed


def srt_timestamp(seconds):
    milliseconds = max(0, round(float(seconds)*1000))
    hours, rem = divmod(milliseconds, 3600000)
    minutes, rem = divmod(rem, 60000)
    secs, ms = divmod(rem, 1000)
    return f'{hours:02}:{minutes:02}:{secs:02},{ms:03}'

def export_subtitles(rows, path):
    path = Path(path)
    blocks=[]
    # A failed translation is explicitly marked, never presented as Chinese text.
    for row in rows:
        if row.get('manual'):
            continue
        text = row.get('zh') if row.get('ok') else '【翻译失败，保留日文】'
        blocks.append(f"{len(blocks)+1}\n{srt_timestamp(row['start'])} --> {srt_timestamp(row['end'])}\n{text}\n{row['ja']}\n")
    path.write_text('\n'.join(blocks),encoding='utf-8')

class ModelServer:
    def __init__(self, port=8181, backend='auto', cpu_threads=8, log_name='模型启动日志.txt', gpu_layers=None):
        self.port=port
        self.backend=backend
        self.cpu_threads=cpu_threads
        self.log_name=log_name
        self.gpu_layers=gpu_layers
        self.api_key=secrets.token_urlsafe(32)
        self.process=None
        self.log=None
        self.lock=threading.Lock()
        self.closed=False
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.opener.addheaders=[("Authorization","Bearer "+self.api_key)]
    def start(self):
        with self.lock:
            if self.closed:
                raise RuntimeError('程序已关闭')
            requested_backend=self.backend
            use_hybrid=self.backend in ('hybrid','hybrid_lowvram')
            use_cuda = self.backend == 'cuda' or use_hybrid or (self.backend == 'auto' and (BASE/'cuda_ready.json').is_file())
            use_cpu = self.backend == 'cpu'
            if self.backend not in ('auto','cuda','vulkan','cpu','hybrid','hybrid_lowvram'):
                raise ValueError('请选择有效的中文翻译设备')
            threads=int(self.cpu_threads) if use_cpu or use_hybrid else 8
            if not 1<=threads<=64:raise ValueError('CPU 翻译线程应为 1 到 64')
            default_layers=24 if requested_backend=='hybrid' else (16 if requested_backend=='hybrid_lowvram' else 99)
            gpu_layers=0 if use_cpu else (default_layers if self.gpu_layers is None else int(self.gpu_layers))
            if not 0<=gpu_layers<=999:raise ValueError('GPU 模型层数应为 0 到 999')
            directory=BASE/('llama-cuda' if use_cuda or (use_cpu and (BASE/'llama-cuda').is_dir()) else 'llama')
            executables=list(directory.rglob('llama-server.exe'))
            model=BASE/'models'/'asmr-zh-cn-q4_k_m.gguf'
            if not executables or not model.exists():
                raise RuntimeError('本地翻译运行时或模型尚未准备完成')
            with socket.socket() as check:
                try:
                    check.bind(('127.0.0.1',self.port))
                except OSError as exc:
                    raise RuntimeError(f'本机端口 {self.port} 已被占用，请关闭其他翻译器后重试') from exc
            exe=executables[0]
            self.backend='CPU' if use_cpu else ('CUDA' if use_cuda else 'Vulkan')
            if use_hybrid:self.backend='CUDA＋CPU 混合（均衡）' if requested_backend=='hybrid' else 'CUDA＋CPU 混合（省显存）'
            args=[str(exe),'-m',str(model),'--host','127.0.0.1','--port',str(self.port),
                  '--device','none' if use_cpu else ('CUDA0' if use_cuda else 'Vulkan0'),
                  '-ngl',str(gpu_layers),'-c','2048','-b','256','-ub','128','-np','1','--alias','asmr-ja-zh',
                  '-t',str(threads),'-tb',str(threads),'--poll','0','--threads-http','2','--jinja','--no-webui']
            if use_cuda:
                args.extend(['-fa','on'])
            self.log=(BASE/'work'/self.log_name).open('w',encoding='utf-8')
            child_env=os.environ.copy()
            child_env['LLAMA_API_KEY']=self.api_key
            if use_cpu:child_env['CUDA_VISIBLE_DEVICES']='-1'
            self.process=subprocess.Popen(args,cwd=exe.parent,env=child_env,stdin=subprocess.DEVNULL,
                stdout=self.log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
            process=self.process
        deadline=time.monotonic()+150
        while time.monotonic()<deadline:
            if process.poll() is not None:
                raise RuntimeError('翻译模型启动失败，请查看 work\\模型启动日志.txt')
            with self.lock:
                if self.closed:
                    raise RuntimeError('程序已关闭')
            try:
                with self.opener.open(f'http://127.0.0.1:{self.port}/health',timeout=1) as response:
                    if response.status==200:
                        return
            except Exception:
                pass
            time.sleep(0.3)
        self.close()
        raise RuntimeError('本地模型加载超时')
    def close(self):
        with self.lock:
            self.closed=True
            if self.process and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=3)
            if self.log:
                self.log.close()
                self.log=None

class LoopbackCapture:
    def __init__(self, device, options, submit, emit, clock):
        self.device=dict(device)
        self.options=dict(options)
        self.submit=submit
        self.emit=emit
        self.clock=clock
        self.stop_event=threading.Event()
        self.thread=None
        self.stream=None
    def start(self):
        if not self.device.get('isLoopbackDevice'):
            raise ValueError('只能选择播放回环设备')
        self.thread=threading.Thread(target=self._run,name='PlaybackCapture',daemon=True)
        self.thread.start()
    def stop(self):
        self.stop_event.set()
        thread=self.thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=2)
            if thread.is_alive():
                raise RuntimeError('音频设备未及时关闭，请退出程序释放设备')
    def _run(self):
        audio=None
        try:
            from faster_whisper.vad import get_vad_model
            vad=get_vad_model()
            audio=pyaudio.PyAudio()
            self.device=resolve_loopback_device(audio,self.device)
            rate=int(self.device['defaultSampleRate'])
            channels=min(2,int(self.device['maxInputChannels']))
            frames=round(rate*0.1)
            self.stream=audio.open(format=pyaudio.paInt16,channels=channels,rate=rate,input=True,
                input_device_index=int(self.device['index']),frames_per_buffer=frames)
            self.emit('capture_open',None)
            pre=deque(maxlen=4)
            sliding=deque(maxlen=10)
            phrase=[]
            quiet=0.0
            duration=0.0
            begin=0.0
            thresholds={'标准':0.35,'耳语':0.22,'强降误识别':0.55}
            threshold=thresholds.get(self.options.get('sensitivity'),0.35)
            while not self.stop_event.is_set():
                raw=self.stream.read(frames,exception_on_overflow=False)
                block=np.frombuffer(raw,dtype=np.int16).reshape(-1,channels).astype(np.float32)/32768
                now=time.monotonic()
                sliding.append(block)
                probe=mono_resample(np.concatenate(sliding),rate)
                peak=float(np.max(np.abs(probe))) if probe.size else 0.0
                # A bounded gain helps whispers without boosting silence into speech.
                probe=probe*min(4.0,0.2/max(peak,0.01))
                padded=np.pad(probe,(0,(-len(probe))%512))
                probabilities=vad(padded).reshape(-1)
                speaking=bool(peak>0.00035 and np.max(probabilities[-4:])>=threshold)
                length=len(block)/rate
                if not phrase:
                    pre.append(block)
                    if not speaking:
                        continue
                    phrase=list(pre)
                    duration=sum(len(x) for x in phrase)/rate
                    begin=max(0.0,now-self.clock-duration)
                    pre.clear()
                    quiet=0.0
                else:
                    phrase.append(block)
                    duration+=length
                    quiet=0.0 if speaking else quiet+length
                if quiet>=float(self.options.get('pause',0.35)) or duration>=float(self.options.get('max_phrase',3.0)):
                    if not self.stop_event.is_set():
                        self.submit(mono_resample(np.concatenate(phrase),rate),begin,begin+duration)
                    phrase=[]
                    duration=quiet=0.0
                    pre.clear()
        except Exception as exc:
            if not self.stop_event.is_set():
                self.emit('capture_error',capture_error_message(exc,self.device))
        finally:
            if self.stream:
                try:
                    self.stream.stop_stream()
                    self.stream.close()
                except OSError:
                    pass
                self.stream=None
            if audio:
                audio.terminate()
            self.emit('capture_closed',None)

class CaptionEngine:
    def __init__(self,emit):
        self.emit=emit
        try:runtime=load_config()
        except Exception:runtime=DEFAULTS
        backend=runtime.get('translation_backend','auto')
        self.server=ModelServer(backend=backend,cpu_threads=runtime.get('cpu_llm_threads',8))
        self.translation_timeout=60 if backend=='cpu' else 25
        self.model=None
        self.ready=False
        self.closed=False
        self.epoch=0
        self.state_lock=threading.RLock()
        self.work=RouteTranscriptionQueue()
        self.translation_work=RouteTranscriptionQueue()
        self.client=LocalASMRClient(timeout=self.translation_timeout,api_key=self.server.api_key,prefill=True)
        self.capture=None
        self.clock=None
        self.options=dict(DEFAULTS)
        self.worker=threading.Thread(target=self._recognize_worker,name='CaptionRecognition',daemon=True)
        self.worker.start()
        self.translation_worker=threading.Thread(target=self._translate_worker,name='CaptionTranslation',daemon=True)
        self.translation_worker.start()
    def prepare(self):
        def run():
            try:
                self.emit('status','正在加载本地模型，尚未接收声音…')
                from faster_whisper import WhisperModel
                directory=BASE/'models'/'whisper-small'
                if not (directory/'model.bin').exists():
                    raise RuntimeError('日语识别模型尚未准备完成')
                self.model=WhisperModel(str(directory),device='cpu',compute_type='int8',cpu_threads=8,
                    num_workers=1,local_files_only=True)
                self.server.start()
                self.emit('status','正在预热本地翻译模型，尚未接收声音…')
                self.client.translate('今日は休みです。',context=False,cancelled=lambda:self.closed)
                self.client.clear()
                with self.state_lock:
                    if self.closed:
                        return
                    self.ready=True
                self.emit('ready',self.server.backend)
            except Exception as exc:
                if not self.closed:
                    self.emit('prepare_error',str(exc))
        threading.Thread(target=run,name='LocalModelLoader',daemon=True).start()
    def _valid(self,epoch):
        with self.state_lock:
            return not self.closed and epoch==self.epoch
    def start(self,device,options):
        with self.state_lock:
            if not self.ready or self.closed:
                raise RuntimeError('本地模型尚未就绪')
            if self.capture is not None:
                raise RuntimeError('请先停止当前设备')
            self.epoch+=1
            epoch=self.epoch
            self.options=dict(options)
            # Preserve context between phrases, but invalidate it after stopping/changing works.
            self.client=LocalASMRClient(timeout=self.translation_timeout,api_key=self.server.api_key,prefill=True)
            if self.clock is None:
                self.clock=time.monotonic()
            def submit(data,start,end):
                with self.state_lock:
                    if not self._valid(epoch):
                        return
                    if self.work.source_size('main')+self.translation_work.source_size('main')>=5:
                        raise RuntimeError('处理速度跟不上播放，已停止收音并清空积压；请从刚才位置重播或放慢播放')
                    self.work.put({'source_id':'main','final':True,'epoch':epoch,
                        'audio':data,'start':start,'end':end,'options':dict(options),'manual':False,
                        'submitted_at':time.monotonic()})
            def event(kind,value):
                if self._valid(epoch):
                    self.emit(kind,value)
            self.capture=LoopbackCapture(device,options,submit,event,self.clock)
            self.capture.start()
    def stop(self):
        with self.state_lock:
            self.epoch+=1
            self.work.discard_source('main')
            self.translation_work.discard_source('main')
            self.client=LocalASMRClient(timeout=self.translation_timeout,api_key=self.server.api_key,prefill=True)
            capture=self.capture
            self.capture=None
        if capture:
            capture.stop()
        self.emit('stopped',None)
    def reset(self):
        self.stop()
        self.clock=None
        self.client=LocalASMRClient(timeout=self.translation_timeout,api_key=self.server.api_key,prefill=True)
    def translate_manual(self,text,options):
        if not self.ready or self.closed:
            raise RuntimeError('本地模型尚未就绪')
        if self.capture:
            raise RuntimeError('请停止收音后再测试输入')
        self.work.put({'source_id':'main','final':True,'epoch':self.epoch,'text':text,
            'start':0,'end':1,'options':dict(options),'manual':True})
    def _recognize_worker(self):
        while not self.closed:
            try:
                item=self.work.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                epoch=item['epoch']
                with self.state_lock:
                    if not self._valid(epoch):
                        continue
                t=time.monotonic()
                repetition_shortened=False
                if item['manual']:
                    source=item['text'].strip()
                    asr_time=0.0
                else:
                    self.emit('status','正在本机识别日语…')
                    waveform=item['audio']
                    if non_speech_reason(waveform):
                        continue
                    peak=float(np.max(np.abs(waveform)))
                    waveform=waveform*min(4.0,0.3/max(peak,0.01))
                    threshold={'标准':0.35,'耳语':0.22,'强降误识别':0.55}.get(item['options'].get('sensitivity'),0.35)
                    segments,info=self.model.transcribe(waveform,language='ja',task='transcribe',
                        beam_size=1 if item['options'].get('fast_asr',True) else 3,temperature=0.0,condition_on_previous_text=False,
                        vad_filter=True,vad_parameters={'threshold':threshold,'min_speech_duration_ms':120,
                            'min_silence_duration_ms':400,'speech_pad_ms':200},
                        no_speech_threshold=0.6,log_prob_threshold=-1.0,compression_ratio_threshold=2.4)
                    source=''.join(s.text for s in segments).strip()
                    asr_time=time.monotonic()-t
                    source,repetition_shortened=normalize_asr_repetition(source)
                    if repetition_shortened and self._valid(epoch):
                        self.emit('status','已压缩异常重复的笑声 / 气声文字。' if source
                                  else '已跳过仅含长串重复笑声 / 气声的识别结果。')
                if not source or not self._valid(epoch):
                    continue
                row={'epoch':epoch,'ja':source,'zh':'','ok':False,'start':item['start'],
                    'end':item['end'],'manual':item['manual'],'asr_seconds':asr_time,
                    'asr_repetition_shortened':repetition_shortened,
                    'options':item['options'],'submitted_at':item.get('submitted_at'),
                    'source_id':'main','final':True}
                with self.state_lock:
                    if self._valid(epoch):
                        if self.translation_work.source_size('main')>=5:
                            self.emit('capture_error','翻译速度跟不上播放，已停止收音；请从刚才位置重播')
                        else:
                            self.translation_work.put(row)
            except Exception as exc:
                if self._valid(item['epoch']):
                    self.emit('inference_error',str(exc))
            finally:
                self.work.task_done()
    def _translate_worker(self):
        while not self.closed:
            try:
                row=self.translation_work.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                epoch=row['epoch']
                with self.state_lock:
                    if not self._valid(epoch):
                        continue
                    client=self.client
                options=row.pop('options')
                submitted_at=row.pop('submitted_at')
                source=row['ja']
                row.pop('source_id');row.pop('final')
                self.emit('original',dict(row))
                self.emit('status','正在本机翻译…')
                try:
                    def partial(text):
                        if self._valid(epoch):
                            if submitted_at and 'first_caption_seconds' not in row:
                                row['first_caption_seconds']=time.monotonic()-submitted_at
                            self.emit('partial',{**row,'zh':text})
                    row['zh']=client.translate(source,glossary=options['glossary'],
                        scene=options['scene'],context=options['context'],
                        on_partial=partial,cancelled=lambda:not self._valid(epoch))
                    row['ok']=True
                    row['translate_seconds']=client.last_latency
                    row['first_text_seconds']=client.first_text_latency
                    if submitted_at:
                        row['complete_caption_seconds']=time.monotonic()-submitted_at
                except Exception as exc:
                    row['error']=str(exc)
                if self._valid(epoch):
                    self.emit('caption',row)
            except Exception as exc:
                if self._valid(row['epoch']):
                    self.emit('inference_error',str(exc))
            finally:
                self.translation_work.task_done()
    def close(self):
        self.stop()
        with self.state_lock:
            self.closed=True
        self.server.close()
        for worker in (self.worker,self.translation_worker):
            if worker is not threading.current_thread():
                worker.join(timeout=1)
