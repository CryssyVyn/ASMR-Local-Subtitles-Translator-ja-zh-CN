import json
import io
import tempfile
import unittest
from unittest.mock import patch,MagicMock
import threading
import time
from pathlib import Path
import numpy as np
from asmr_chinese_plugin import parse_translation, validate_glossary, partial_translation, LocalASMRClient, TranslationCancelled
from realtime_core import mono_resample, non_speech_reason, normalize_asr_repetition, export_subtitles, LoopbackCapture, CaptionEngine, ModelServer, DEFAULTS, resolve_loopback_device, capture_error_message
from vendor.whispering_tiger.transcription_queue import RouteTranscriptionQueue

class SafetyTests(unittest.TestCase):
    def test_hybrid_translation_preserves_requested_cuda_layer_count(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            (base/'llama-cuda').mkdir();(base/'models').mkdir();(base/'work').mkdir()
            (base/'llama-cuda'/'llama-server.exe').touch()
            (base/'models'/'asmr-zh-cn-q4_k_m.gguf').touch()
            with patch('realtime_core.BASE',base),patch('realtime_core.subprocess.Popen') as launch:
                launch.return_value.poll.return_value=None
                server=ModelServer(port=0,backend='cuda',gpu_layers=24)
                health=MagicMock();health.__enter__.return_value.status=200
                server.opener.open=MagicMock(return_value=health)
                try:
                    server.start()
                    args=launch.call_args.args[0]
                    self.assertEqual(args[args.index('--device')+1],'CUDA0')
                    self.assertEqual(args[args.index('-ngl')+1],'24')
                    self.assertEqual(args[args.index('-fa')+1],'on')
                    self.assertEqual(server.backend,'CUDA')
                finally:server.close()

    def test_hybrid_presets_select_tested_layer_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            (base/'llama-cuda').mkdir();(base/'models').mkdir();(base/'work').mkdir()
            (base/'llama-cuda'/'llama-server.exe').touch()
            (base/'models'/'asmr-zh-cn-q4_k_m.gguf').touch()
            for backend,layers in (('hybrid',24),('hybrid_lowvram',16)):
                with self.subTest(backend=backend),patch('realtime_core.BASE',base),patch('realtime_core.subprocess.Popen') as launch:
                    launch.return_value.poll.return_value=None
                    server=ModelServer(port=0,backend=backend,cpu_threads=12)
                    health=MagicMock();health.__enter__.return_value.status=200
                    server.opener.open=MagicMock(return_value=health)
                    try:
                        server.start()
                        args=launch.call_args.args[0]
                        self.assertEqual(args[args.index('--device')+1],'CUDA0')
                        self.assertEqual(args[args.index('-ngl')+1],str(layers))
                        self.assertEqual(args[args.index('-t')+1],'12')
                        self.assertIn('混合',server.backend)
                    finally:server.close()

    def test_cpu_server_disables_offload_and_uses_selected_threads(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            (base/'llama-cuda').mkdir();(base/'models').mkdir();(base/'work').mkdir()
            (base/'llama-cuda'/'llama-server.exe').touch()
            (base/'models'/'asmr-zh-cn-q4_k_m.gguf').touch()
            with patch('realtime_core.BASE',base),patch('realtime_core.subprocess.Popen') as launch:
                launch.return_value.poll.return_value=None
                server=ModelServer(port=0,backend='cpu',cpu_threads=12)
                health=MagicMock();health.__enter__.return_value.status=200
                server.opener.open=MagicMock(return_value=health)
                try:
                    server.start()
                    args=launch.call_args.args[0]
                    self.assertEqual(args[args.index('--device')+1],'none')
                    self.assertEqual(args[args.index('-ngl')+1],'0')
                    self.assertEqual(args[args.index('-t')+1],'12')
                    self.assertEqual(args[args.index('-tb')+1],'12')
                    self.assertNotIn('-fa',args)
                    self.assertEqual(launch.call_args.kwargs['env']['CUDA_VISIBLE_DEVICES'],'-1')
                    self.assertEqual(launch.call_args.kwargs['env']['LLAMA_API_KEY'],server.api_key)
                    self.assertEqual(server.backend,'CPU')
                finally:server.close()

    def test_cpu_selection_survives_engine_stop_and_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder)
            (base/'作品设置.json').write_text(json.dumps({'translation_backend':'cpu','cpu_llm_threads':12}),encoding='utf-8')
            with patch('realtime_core.BASE',base):
                engine=CaptionEngine(lambda *args:None)
                try:
                    self.assertEqual(engine.server.backend,'cpu')
                    self.assertEqual(engine.server.cpu_threads,12)
                    self.assertEqual(engine.client.timeout,60)
                    engine.stop();self.assertEqual(engine.client.timeout,60)
                    engine.reset();self.assertEqual(engine.client.timeout,60)
                finally:engine.close()

    def test_extreme_sound_loops_are_skipped_but_normal_repetition_is_preserved(self):
        for source in ('ふっ'*150+'ふ', 'ふっ、'*100, '哈哈'*100, 'はぁ。'*60, 'くすくす'*30):
            self.assertEqual(normalize_asr_repetition(source),('',True))
        for source in ('ふっふっふっ。', 'ふっ'*5, 'はぁ、今日は疲れた。', 'はい、'*20,
                       '好き'*80, 'そうそう、そうなんです。'):
            self.assertEqual(normalize_asr_repetition(source),(source,False))
        source='ふっ'*120+'今日はゆっくり休んでください。'
        self.assertEqual(normalize_asr_repetition(source),
                         ('ふっふっふっ…今日はゆっくり休んでください。',True))

    def test_sound_loop_never_reaches_translator_but_mixed_dialogue_does(self):
        done=threading.Event();captions=[];sources=[];statuses=[]
        class Model:
            calls=0
            def transcribe(self,*args,**kwargs):
                self.calls+=1
                text='ふっ'*150 if self.calls==1 else 'ふっ'*150+'今日は休みです。'
                return ([type('Segment',(),{'text':text})()],None)
        class Client:
            last_latency=.1;first_text_latency=.05
            def translate(self,source,**kwargs):
                sources.append(source)
                return '呵呵，今天休息。'
        def emit(kind,value):
            if kind=='status':statuses.append(value)
            if kind=='caption':captions.append(value);done.set()
        engine=CaptionEngine(emit)
        try:
            engine.model=Model();engine.client=Client()
            wave=np.random.default_rng(5).normal(0,.01,16000).astype(np.float32)
            item={'source_id':'main','final':True,'epoch':engine.epoch,'audio':wave,
                  'start':0,'end':1,'options':dict(DEFAULTS),'manual':False}
            engine.work.put(dict(item));engine.work.put(dict(item))
            self.assertTrue(done.wait(2),'Mixed dialogue was not translated')
            self.assertEqual(sources,['ふっふっふっ…今日は休みです。'])
            self.assertEqual(len(captions),1)
            self.assertTrue(captions[0]['ok'])
            self.assertTrue(captions[0]['asr_repetition_shortened'])
            self.assertTrue(any('已跳过' in status for status in statuses))
        finally:
            engine.close()

    def test_capture_resolves_changed_device_index_without_switching_device(self):
        class Audio:
            def get_loopback_device_info_generator(self):
                return iter([{'name':'Other [Loopback]','index':27},
                             {'name':'Headphones [Loopback]','index':28}])
        selected={'name':'Headphones [Loopback]','index':27}
        self.assertEqual(resolve_loopback_device(Audio(),selected)['index'],28)
        with self.assertRaisesRegex(ValueError,'刷新'):
            resolve_loopback_device(Audio(),{'name':'Disconnected [Loopback]','index':28})

    def test_invalid_device_message_explains_recovery(self):
        message=capture_error_message(OSError(-9996,'Invalid device'),{'name':'Speakers [Loopback]'})
        self.assertIn('Speakers [Loopback]',message)
        self.assertIn('刷新',message)
        self.assertIn('-9996',message)
        self.assertEqual(capture_error_message(OSError(-9981,'Overflow'),{}),str(OSError(-9981,'Overflow')))

    def test_recognition_continues_while_previous_translation_is_running(self):
        started=threading.Event();release=threading.Event();second=threading.Event()
        class Model:
            calls=0
            def transcribe(self,*args,**kwargs):
                self.calls+=1
                if self.calls==2:second.set()
                return ([type('Segment',(),{'text':'今日は休みです。'})()],None)
        class Client:
            last_latency=.1;first_text_latency=.05
            def translate(self,*args,**kwargs):
                started.set();release.wait(2);return '今天休息。'
        engine=CaptionEngine(lambda *args:None)
        try:
            engine.model=Model();engine.client=Client()
            wave=np.random.default_rng(1).normal(0,.01,16000).astype(np.float32)
            base={'source_id':'main','final':True,'epoch':engine.epoch,'audio':wave,'start':0,
                  'end':1,'options':dict(DEFAULTS),'manual':False,'submitted_at':time.monotonic()}
            engine.work.put(dict(base))
            self.assertTrue(started.wait(1))
            engine.work.put(dict(base))
            self.assertTrue(second.wait(1),'Next speech was blocked by the previous translation')
            engine.stop();self.assertEqual(engine.work.qsize()+engine.translation_work.qsize(),0)
        finally:
            release.set();engine.close()
    def test_stream_draft_decodes_escapes_and_never_echo(self):
        self.assertEqual(partial_translation('[{"text":"今天'), '今天')
        self.assertEqual(partial_translation('[{"text":"今天\\u4f'), '今天')
        self.assertEqual(partial_translation('[{"text":"今天\\u4f11'), '今天休')
        self.assertEqual(partial_translation('[{"text":"他说\\"好\\"。","ids":'), '他说"好"。')
        self.assertEqual(partial_translation('[{"input":"今日は休みです。","text":"今天'), '今天')
        self.assertEqual(partial_translation('[{"input":"\\"text\\":\\"伪字幕'), '')
    def test_stream_has_drafts_but_commits_only_valid_complete_echo(self):
        source='今日は休みです。'
        raw=json.dumps([{'text':'今天休息。','ids':[1],'input':source,'start':0,'end':1}],ensure_ascii=False)
        client,response=self.stream_client(raw)
        drafts=[]
        self.assertEqual(client.translate(source,on_partial=drafts.append),'今天休息。')
        self.assertTrue(drafts);self.assertEqual(drafts[-1],'今天休息。')
        self.assertEqual(client.history[-1]['zh'],'今天休息。')
        self.assertTrue(response.closed)
        for invalid in [raw.replace(source,'別の言葉'), raw[:-3]]:
            client,_=self.stream_client(invalid)
            with self.assertRaises(RuntimeError):client.translate(source,on_partial=lambda x:None)
            self.assertFalse(client.history)
    def test_stream_cancel_releases_connection_and_does_not_commit(self):
        source='今日は休みです。'
        raw=json.dumps([{'text':'今天休息。','ids':[1],'input':source,'start':0,'end':1}],ensure_ascii=False)
        client,response=self.stream_client(raw)
        stopped=[]
        with self.assertRaises(TranslationCancelled):
            client.translate(source,on_partial=lambda x:stopped.append(True),cancelled=lambda:bool(stopped))
        self.assertTrue(response.closed);self.assertFalse(client.history)
    def test_stream_eof_and_token_limit_are_not_final_subtitles(self):
        source='今日は休みです。'
        raw=json.dumps([{'text':'今天休息。','ids':[1],'input':source,'start':0,'end':1}],ensure_ascii=False)
        for finish,done in [('length',True),('stop',False)]:
            client,_=self.stream_client(raw,finish,done)
            with self.assertRaises(RuntimeError):client.translate(source)
            self.assertFalse(client.history)
    def test_prefill_uses_current_source_and_server_echo_is_not_duplicated(self):
        source='彼は"大丈夫"と言った。'
        raw=json.dumps([{'ids':[1],'input':source,'text':'他说“没事”。','start':0,'end':1}],ensure_ascii=False)
        client,response=self.stream_client(raw)
        client.prefill=True
        opener=client.opener;requests=[]
        class Inspect:
            def open(self,request,timeout):
                requests.append(json.loads(request.data));return opener.open(request,timeout)
        client.opener=Inspect()
        self.assertEqual(client.translate(source),'他说“没事”。')
        body=requests[0]
        self.assertNotIn('response_format',body)
        self.assertIn('root ::= char*',body['grammar'])
        prefix=body['messages'][-1]
        self.assertEqual(prefix['role'],'assistant')
        self.assertEqual(json.loads(prefix['content']+'x","start":0,"end":1}]')[0]['input'],source)
    @staticmethod
    def stream_client(raw,finish='stop',done=True):
        lines=[]
        for char in raw:
            lines.append('data: '+json.dumps({'choices':[{'delta':{'content':char},'finish_reason':None}]},ensure_ascii=False)+'\n\n')
        lines.append('data: '+json.dumps({'choices':[{'delta':{},'finish_reason':finish}]})+'\n\n')
        if done:lines.append('data: [DONE]\n\n')
        response=io.BytesIO(''.join(lines).encode('utf-8'))
        class Opener:
            def open(self,request,timeout):return response
        client=LocalASMRClient();client.opener=Opener()
        return client,response
    def test_echo_validation_preserves_correct_phrase(self):
        source='今日は休みです。'
        raw=json.dumps([{'ids':[1],'input':source,'text':'今天休息。','start':0,'end':1}],ensure_ascii=False)
        self.assertEqual(parse_translation(raw,source),'今天休息。')
        for corrupt in [raw.replace(source,'別の言葉'),json.dumps([{'ids':[2],'input':source,'text':'今天休息。'}]),'[]','not JSON']:
            with self.assertRaises(RuntimeError):parse_translation(corrupt,source)
    def test_glossary_validation(self):
        for value in [{},[{'ja':1,'zh':'甲'}],[{'ja':'甲'}],[{'ja':'甲','zh':'乙'}]*5001]:
            with self.assertRaises(ValueError):validate_glossary(value)
    def test_translation_prompt_keeps_contextual_notes_and_excludes_unrelated_terms(self):
        source='旦那様、今日はゆっくり休んでください。'
        raw=json.dumps([{'ids':[1],'input':source,'text':'老公，今天请好好休息。','start':0,'end':1}],ensure_ascii=False)
        client,_=self.stream_client(raw)
        client.history.append({'ja':'先輩、元気ですか。','zh':'前辈，你好吗？'})
        opener=client.opener;requests=[]
        class Inspect:
            def open(self,request,timeout):
                requests.append(json.loads(request.data));return opener.open(request,timeout)
        client.opener=Inspect()
        terms=[{'ja':f'无关词{i}','zh':'无关译法'} for i in range(326)]
        terms += [{'ja':'旦那様','zh':'老爷'},
                  {'ja':'旦那様','zh':'老爷 / 老公','usage_note':'管家语境用老爷；夫妻语境用老公。'},
                  {'ja':'先輩','zh':'前辈'}]
        self.assertEqual(client.translate(source,glossary=terms,scene='夫妻',context=True),'老公，今天请好好休息。')
        prompt=requests[0]['messages'][0]['content']
        line=next(line for line in prompt.splitlines() if line.startswith('多义词与拟声词参考：'))
        self.assertEqual(json.loads(line.split('：',1)[1]),[terms[-2]])
        self.assertIn('usage_note',prompt)
        self.assertIn('禁止把多个候选并列输出',prompt)
        self.assertNotIn('无关译法',prompt)
        self.assertIn('常用译法参考：[]',prompt)  # Old context must not consume reference slots.
    def test_binaural_does_not_cancel_opposite_phase(self):
        wave=np.sin(np.arange(48000)*0.1).astype(np.float32)*0.1
        stereo=np.stack([wave,-wave],axis=1)
        result=mono_resample(stereo,48000)
        self.assertEqual(len(result),16000)
        self.assertGreater(float(np.max(np.abs(result))),0.09)
    def test_binaural_speech_switching_ears_is_preserved(self):
        left=np.zeros(16000,dtype=np.float32)
        right=np.zeros(16000,dtype=np.float32)
        left[:8000]=0.1*np.sin(np.arange(8000)*0.1)
        right[8000:]=0.1*np.sin(np.arange(8000)*0.2)
        output=mono_resample(np.stack([left,right],axis=1),16000)
        self.assertGreater(float(np.max(np.abs(output[:8000]))),0.045)
        self.assertGreater(float(np.max(np.abs(output[8000:]))),0.045)
    def test_silence_and_pure_tone_not_sent_to_asr(self):
        self.assertEqual(non_speech_reason(np.zeros(16000,dtype=np.float32)), 'silence')
        wave=np.sin(np.arange(16000)*2*np.pi*440/16000).astype(np.float32)*0.02
        self.assertEqual(non_speech_reason(wave), 'tone')
    def test_queue_stop_discards_backlog(self):
        q=RouteTranscriptionQueue()
        q.put({'source_id':'main','final':True,'text':'one'})
        q.put({'source_id':'main','final':True,'text':'two'})
        self.assertEqual(q.discard_source('main'),2)
        self.assertEqual(q.qsize(),0)
        q.join()
    def test_microphone_is_rejected_before_stream_open(self):
        capture=LoopbackCapture({'isLoopbackDevice':False},{},lambda *a:None,lambda *a:None,0)
        with self.assertRaises(ValueError):capture.start()
        self.assertIsNone(capture.thread)
    def test_engine_does_not_open_capture_on_construction(self):
        engine=CaptionEngine(lambda *a:None)
        self.assertIsNone(engine.capture)
        self.assertFalse(engine.ready)
        epoch=engine.epoch
        engine.stop()
        self.assertFalse(engine._valid(epoch))
        engine.close()
    def test_stop_during_translation_discards_late_result_and_context(self):
        started=threading.Event();release=threading.Event();captions=[]
        class BlockedClient:
            history=['old context']
            last_latency=0.1
            def translate(self,*args,**kwargs):
                started.set();release.wait(2);return '今天休息。'
        engine=CaptionEngine(lambda kind,value:captions.append(value) if kind=='caption' else None)
        try:
            engine.ready=True;engine.client=BlockedClient()
            engine.translate_manual('今日は休みです。',dict(DEFAULTS))
            self.assertTrue(started.wait(1))
            engine.stop();self.assertFalse(engine.client.history)
            release.set();time.sleep(0.2)
            self.assertFalse(captions)
        finally:
            release.set();engine.close()
    def test_export_failure_is_visible_and_manual_tests_excluded(self):
        with tempfile.TemporaryDirectory() as temp:
            target=Path(temp)/'captions.srt'
            rows=[{'start':1.25,'end':2.5,'ja':'原文','zh':'译文','ok':True},
                  {'start':3,'end':4,'ja':'失敗','zh':'','ok':False},
                  {'start':0,'end':1,'ja':'测试','zh':'测试','ok':True,'manual':True}]
            export_subtitles(rows,target)
            result=target.read_text(encoding='utf-8')
            self.assertIn('00:00:01,250 --> 00:00:02,500',result)
            self.assertIn('【翻译失败，保留日文】',result)
            self.assertNotIn('测试',result)

if __name__=='__main__':unittest.main(verbosity=2)
