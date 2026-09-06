const {test} = require('node:test');
const assert = require('node:assert/strict');
const {fork} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {once} = require('node:events');
const fixture = path.resolve(__dirname,'../../tests/fixtures/backend_lifetime_process.cjs');
function message(child, kind) {
  return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>{child.off('message',onMessage); reject(Error(`Timed out: ${kind}`));},5000);
    function onMessage(msg) {if(msg.kind===kind){clearTimeout(timer);child.off('message',onMessage);resolve(msg);}}
    child.on('message',onMessage);
  });
}
test('real child task survives client exit and second client attaches same boot; drift and death refuse without replay', async t=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'backend-lifetime-'));
  const host=fork(fixture,['host',dir],{stdio:['ignore','ignore','inherit','ipc']});
  const hostExit=once(host,'exit');
  t.after(async()=>{if(host.exitCode===null && host.signalCode===null) host.send({kind:'stop'});await hostExit;fs.rmSync(dir,{recursive:true,force:true});});
  await message(host,'ready');
  const original=JSON.parse(fs.readFileSync(path.join(dir,'receipt')));
  const started=message(host,'started');host.send({kind:'start'});await started;
  async function client({drift=false,dead=false}={}) {
    const driftPath=path.join(dir,'drift');
    if(drift) fs.writeFileSync(driftPath,'changed');
    else if(fs.existsSync(driftPath)) fs.unlinkSync(driftPath);
    const child=fork(fixture,['client',dir],{stdio:['ignore','ignore','inherit','ipc']});
    const exited=once(child,'exit');
    let probes=0;
    const relay=msg=>{if(msg.kind==='response' && child.connected) child.send(msg);};
    host.on('message',relay);
    child.on('message',msg=>{if(msg.kind==='probe'){
      probes++;
      assert.equal(msg.headers['X-Harness-Boot'],original.boot_id);
      if(dead) child.send({kind:'response',status:503,body:{code:'interrupted'}});
      else host.send({kind:'probe',drift});
    }});
    const [code]=await exited;
    host.off('message',relay);
    assert.equal(probes,process.env.BACKEND_LIFETIME_SOCKET === '1' ? 0 : 1);
    return code;
  }
  assert.equal(await client(),0);
  assert.equal(host.exitCode,null);
  assert.equal(fs.existsSync(path.join(dir,'result')),false);
  assert.equal(await client(),0);
  assert.deepEqual(JSON.parse(fs.readFileSync(path.join(dir,'receipt'))),original);
  const completed=message(host,'completed');fs.writeFileSync(path.join(dir,'release'),'go');await completed;
  assert.equal(fs.readFileSync(path.join(dir,'result'),'utf8'),'completed once');
  assert.equal(await client({drift:true}),2);
  host.send({kind:'stop'});await hostExit;
  assert.equal(await client({dead:true}),2);
  assert.equal(fs.readFileSync(path.join(dir,'result'),'utf8'),'completed once');
});
