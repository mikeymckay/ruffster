import io
import json
import os
from pathlib import Path
import struct
import tempfile
import unittest
from family_activity.browser_channel import Receiver, validate
from family_activity.browser_host import run

class BrowserTests(unittest.TestCase):
    def test_only_domains_accepted(self):
        self.assertEqual(validate({'domain': 'example.com'}), 'example.com')
        self.assertIsNone(validate({'domain': None}))
        for bad in ('https://example.com/private?q=secret', 'example.com/path', 'example.com:443', '127.0.0.1', 'LOCALHOST', 'example.com\n', ''):
            with self.subTest(bad=bad), self.assertRaises(ValueError): validate({'domain': bad})
        with self.assertRaises(ValueError): validate({'domain':'example.com', 'title':'secret'})

    @unittest.skipUnless(hasattr(os, 'getuid'), 'Unix-domain sockets required')
    def test_native_frames_deliver_only_valid_domains(self):
        with tempfile.TemporaryDirectory() as tmp:
            receiver = Receiver(str(Path(tmp)/'socket'))
            try:
                frames = []
                for message in ({'domain':'example.com'}, {'domain':'example.com/private'}, {'domain': None}):
                    data = json.dumps(message).encode(); frames.append(struct.pack('=I', len(data)) + data)
                output = io.BytesIO(); run(io.BytesIO(b''.join(frames)), output, str(Path(tmp)/'socket'))
                self.assertEqual(list(receiver.drain()), ['example.com', None])
                self.assertNotIn(b'example.com/private', output.getvalue())
            finally:
                receiver.close()

    def test_host_manifest_requires_exact_origin_and_quotes_launcher(self):
        from family_activity.browser_manifest import host_manifest, unix_launcher
        manifest = json.loads(host_manifest('/tmp/host', 'a'*32))
        self.assertEqual(manifest['allowed_origins'], ['chrome-extension://' + 'a'*32 + '/'])
        with self.assertRaises(ValueError): host_manifest('/tmp/host', '*')
        script = unix_launcher('/tmp/python', '/tmp/code dir', '/tmp/socket dir/a')
        self.assertIn("'/tmp/code dir'", script)
        self.assertIn("'/tmp/socket dir/a'", script)

    @unittest.skipUnless(hasattr(os, 'getuid'), 'Unix-domain sockets required')
    def test_encrypted_agent_records_synthetic_domain_only(self):
        import sqlite3
        import subprocess
        import sys
        import time
        from nacl.public import PrivateKey
        from family_activity.browser_channel import send
        from family_activity.encrypted_view import open_projection
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp); socket=folder/'browser.sock'; database=folder/'data.db'
            parent=PrivateKey.generate(); public=folder/'parent.pub'; public.write_bytes(bytes(parent.public_key))
            status=folder/'status'
            status.write_text('#!' + sys.executable + '\nimport time\nprint("READY", flush=True)\ntime.sleep(30)\n')
            status.chmod(0o700)
            agent=subprocess.Popen([sys.executable, '-m', 'family_activity', 'agent', '--db', str(database), '--interval', '.2', '--experimental-public-key', str(public), '--experimental-browser-socket', str(socket), '--experimental-status-helper', str(status)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                self.assertIn('Experimental sampling', agent.stdout.readline())
                self.assertIn('Monitoring heartbeat', agent.stdout.readline())
                send(str(socket), {'domain':'synthetic-example.com'})
                time.sleep(.5)
                agent.terminate(); agent.wait(timeout=5)
                self.assertEqual(agent.returncode, 0)
                db,_=open_projection(database,parent)
                self.assertEqual(db.execute('SELECT domain FROM website_samples').fetchall(), [('synthetic-example.com',)])
                db.close()
                self.assertNotIn(b'synthetic-example.com', database.read_bytes())
            finally:
                if agent.poll() is None: agent.kill(); agent.wait()
                agent.stdout.close(); agent.stderr.close()

    def test_browser_strips_paths_and_excludes_private_contexts(self):
        import shutil
        import subprocess
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js is required for extension JavaScript validation')
        script = '''const {domainFromTab} = require('./browser/chromium/domain.js');
const assert = require('assert');
assert.equal(domainFromTab({focused:true,incognito:false}, {url:'https://Example.com/a/private?secret=one#fragment',incognito:false}), 'example.com');
assert.equal(domainFromTab({focused:true,incognito:true}, {url:'https://example.com/',incognito:true}), null);
assert.equal(domainFromTab({focused:false}, {url:'https://example.com/'}), null);
assert.equal(domainFromTab({focused:true}, {url:'http://127.0.0.1/private'}), null);
assert.equal(domainFromTab({focused:true}, {url:'file:///private'}), null);
'''
        subprocess.run([node, '-e', script], check=True, capture_output=True, text=True)

    def test_extension_popup_explains_and_controls_domain_visibility(self):
        import shutil
        import subprocess
        manifest = json.loads((Path(__file__).parents[1] / 'browser/chromium/manifest.json').read_text())
        self.assertIn('storage', manifest['permissions'])
        self.assertEqual(manifest['action']['default_popup'], 'popup.html')
        root = Path(__file__).parents[1] / 'browser/chromium'
        popup = (root / 'popup.html').read_text(encoding='utf-8')
        self.assertIn('domain name only', popup)
        self.assertIn('runs only in this browser on the child\'s computer', popup)
        self.assertIn('Pausing or removing it, or using another browser, can leave gaps', popup)
        self.assertIn('the parent report cannot tell whether sharing was paused, disconnected, or simply had nothing to report', popup)
        self.assertIn('Private-window domains are excluded', popup)
        self.assertIn('for example, wikipedia.org', popup)
        self.assertIn('remembers your pause choice and that sharing was interrupted', popup)
        self.assertNotIn('temporary reset flag', popup)
        self.assertNotIn('domain-free marker', popup)
        self.assertIn('This switch affects website sharing only', popup)
        self.assertIn('<details class="saved">', popup)
        styles = (root / 'popup.css').read_text(encoding='utf-8')
        self.assertIn('.saved summary:focus-visible', styles)
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js is required for extension JavaScript validation')
        subprocess.run([node, '--check', str(root / 'background.js')], check=True, capture_output=True, text=True)
        subprocess.run([node, '--check', str(root / 'popup.js')], check=True, capture_output=True, text=True)
        script = r'''
const fs=require('fs'), vm=require('vm'), assert=require('assert');
const event=()=>{const handlers=[];return {handlers,addListener(fn){handlers.push(fn)},fire(...args){for(const fn of handlers)fn(...args)}}};
const onMessage=event(), ports=[], timers=[], badges=[]; let tick=()=>{}; let saved={websiteObservationsPaused:false};
let focusedWindow={focused:true,incognito:false,id:1};
let activeTab={active:true,incognito:false,url:'https://example.test/private?secret=yes'};
const chrome={
 storage:{local:{get(_defaults,cb){cb(saved)},set(value,cb){saved={...saved,...value};cb()}}},
 action:{setBadgeText(value){badges.push(value.text)},setBadgeBackgroundColor(){},setTitle(){}},
 runtime:{lastError:null,onMessage,onStartup:event(),onInstalled:event(),connectNative(){
   const port={sent:[],onDisconnect:event(),onMessage:event(),postMessage(value){this.sent.push(value)},disconnect(){this.onDisconnect.fire()}};
   ports.push(port);return port;
 }},
 tabs:{onActivated:event(),onUpdated:event(),async query(){return [activeTab]}},windows:{onFocusChanged:event(),async getLastFocused(){return focusedWindow}}
};
const context={chrome,importScripts(){},domainFromTab(){return 'example.test'},setTimeout(fn){timers.push(fn);return timers.length},clearTimeout(){},setInterval(fn){tick=fn}};
vm.runInNewContext(fs.readFileSync('browser/chromium/background.js','utf8'),context);
const wait=()=>new Promise(resolve=>setTimeout(resolve,0));
async function message(value){let result;onMessage.handlers[0](value,{},response=>{result=response});await wait();await wait();return result;}
(async()=>{
 await wait();await wait();assert.equal(ports.length,1);
 ports[0].onMessage.fire({accepted:true});
 let before=ports[0].sent.filter(item=>Object.hasOwn(item,'domain')).length;
 focusedWindow={focused:true,incognito:true,id:2};
 tick();await wait();await wait();assert.equal(ports[0].sent.filter(item=>Object.hasOwn(item,'domain')).length,before);
 focusedWindow={focused:true,incognito:false,id:1};
 activeTab={active:true,incognito:true,get url(){throw new Error('private tab URL must not be read')}};
 tick();await wait();await wait();assert.equal(ports[0].sent.filter(item=>Object.hasOwn(item,'domain')).length,before);
 activeTab={active:true,incognito:false,url:'https://example.test/private?secret=yes'};
 tick();await wait();await wait();
 let observations=ports[0].sent.filter(item=>Object.hasOwn(item,'domain'));
 assert.equal(observations.length,before+2);
 assert.equal(observations.at(-2).domain,null);
 assert.equal(observations.at(-1).domain,'example.test');
 assert.equal(saved.websiteContinuityReset,false);
 before=observations.length;
 const paused=await message({type:'website-visibility-pause',paused:true});assert.equal(paused.paused,true);
 tick();await wait();assert.equal(ports[0].sent.filter(item=>Object.hasOwn(item,'domain')).length,before);
 const resumed=await message({type:'website-visibility-pause',paused:false});assert.equal(resumed.paused,false);
 tick();await wait();assert(ports[0].sent.filter(item=>Object.hasOwn(item,'domain')).length>before);
 assert.equal(saved.websiteObservationsPaused,false);
 ports[0].onDisconnect.fire();
 const disconnected=await message({type:'website-visibility-status'});assert.equal(disconnected.connected,false);
 assert.equal(badges.at(-1),'!');
 assert.equal(timers.length,1);timers.shift()();await wait();await wait();assert.equal(ports.length,2);
 ports[1].onMessage.fire({accepted:true});
 const reconnectSamples=ports[1].sent.filter(item=>Object.hasOwn(item,'domain'));
 assert.equal(reconnectSamples.length,2);assert.equal(reconnectSamples[0].domain,null);assert.equal(reconnectSamples[1].domain,'example.test');
 assert.equal(saved.websiteContinuityReset,false);
 const reconnected=await message({type:'website-visibility-status'});assert.equal(reconnected.connected,true);assert.equal(reconnected.accepted,true);
})().catch(error=>{console.error(error);process.exitCode=1});
'''
        subprocess.run([node, '-e', script], check=True, capture_output=True, text=True, cwd=Path(__file__).parents[1])

    @unittest.skipUnless(hasattr(os, 'getuid'), 'Unix-domain sockets required')
    def test_only_owned_stale_socket_is_removed(self):
        import socket
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp)/'sock')
            active = Receiver(path)
            with self.assertRaises(FileExistsError): Receiver(path)
            active.socket.close()  # Simulate abrupt process death leaving its socket.
            replacement = Receiver(path)
            replacement.close()
            self.assertFalse(Path(path).exists())
            Path(path).write_text('do not remove')
            with self.assertRaises(FileExistsError): Receiver(path)
            self.assertEqual(Path(path).read_text(), 'do not remove')
