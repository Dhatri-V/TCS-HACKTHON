// Opt-in real demo test: RUN_DEMO_LIFECYCLE=1 node scripts/demo-lifecycle.mjs
// Stops ONLY the existing demo PostgreSQL container. Uses isolated real MongoDB.
import assert from 'node:assert/strict';
import { execFile, spawn } from 'node:child_process';
import { promisify } from 'node:util';
import { randomBytes } from 'node:crypto';
import { fileURLToPath } from 'node:url';
import mongoose from 'mongoose';
import { MongoMemoryServer } from 'mongodb-memory-server';
import { createApp } from '../src/app.js';
import { connectDatabase } from '../src/config/database.js';
import { remediationWorker } from '../src/services/remediationWorker.js';
if (process.env.RUN_DEMO_LIFECYCLE !== '1') throw new Error('Set RUN_DEMO_LIFECYCLE=1 to authorize the demo outage test');
const exec = promisify(execFile);
const root = fileURLToPath(new URL('../../../', import.meta.url));
const python = root + 'llm-reasoner/.venv/bin/python';
const env = { PATH:process.env.PATH, HOME:process.env.HOME, PYTHONDONTWRITEBYTECODE:'1',
  PYTHONPATH:root+'llm-reasoner', LITELLM_LOCAL_MODEL_COST_MAP:'True', LLM_PRIMARY_TIMEOUT_SECONDS:'120' };
const rejectAfter=(milliseconds,code)=>new Promise((_,reject)=>{
  const timer=setTimeout(()=>reject(new Error(code)),milliseconds);
  timer.unref();
});
async function py(code, extra={}) {
  const r=await exec(python,['-c',code],{cwd:root,env:{...env,...extra},timeout:600000,maxBuffer:1048576});
  return JSON.parse(r.stdout.trim().split('\n').at(-1));
}
let mongo,server,container,stopped=false,watcher,watcherExit;
const summary={test:'real Docker + real MongoDB + LangGraph + local Qwen',rag:'unavailable; unchanged',checks:[]};
try {
  const snapshot=await py("import json; from llm_reasoner.demo_remediation import DemoDockerAdapter; print(json.dumps(DemoDockerAdapter().snapshot()))");
  assert.equal(snapshot.state,'running');assert.equal(snapshot.health,'healthy');container=snapshot.id;
  const initial=await fetch('http://127.0.0.1:18080/health');assert.equal(initial.status,200);
  mongo=await MongoMemoryServer.create();await connectDatabase(mongo.getUri('isolated_demo_lifecycle'));
  const token=randomBytes(32).toString('hex');let progressObserved=false;
  const app=createApp({remediation:{operatorToken:token,worker:async(payload,onProgress)=>remediationWorker(payload,onProgress?async event=>{
    await onProgress(event);
    const record=await mongoose.connection.collection('incidents').findOne({incident_id:'INC-DEMO-001'});
    assert.equal(record.status,'VERIFYING');assert.equal(record.remediation.state,'VERIFYING');
    progressObserved=true;
  }:undefined)}});
  server=app.listen(0,'127.0.0.1');await new Promise(resolve=>server.once('listening',resolve));
  const base=`http://127.0.0.1:${server.address().port}`;
  const api=async(path,body)=>{
    const r=await fetch(base+'/api/incidents/INC-DEMO-001'+path,{method:body?'POST':'GET',headers:{'Content-Type':'application/json',Authorization:`Bearer ${token}`},...(body?{body:JSON.stringify(body)}:{})});
    return {status:r.status,body:await r.json()};
  };
  const watcherReady=new Promise((resolve,reject)=>{
    watcher=spawn(python,['-m','llm_reasoner.log_watcher','--compose-file',
      root+'demo-infrastructure/compose.yaml','--service','orders-api',
      '--api-base',base,'--demo','--once'],{cwd:root,env});
    watcherExit=new Promise(resolve=>watcher.once('exit',resolve));
    watcher.stdout.setEncoding('utf8');let output='';
    watcher.stdout.on('data',chunk=>{
      output+=chunk;
      for(const line of output.split('\n')){
        try { if(JSON.parse(line).watcher==='ready')resolve(); } catch {}
      }
    });
    watcher.once('error',reject);
  });
  await Promise.race([watcherReady,rejectAfter(10000,'watcher_not_ready')]);
  await exec('docker',['stop',container],{timeout:30000});stopped=true;
  const outage=await fetch('http://127.0.0.1:18080/health');assert.equal(outage.status,503);
  summary.checks.push('PostgreSQL stopped; orders-api returned HTTP 503');
  console.log('Outage confirmed; watcher is processing the real application error.');
  const watcherCode=await Promise.race([
    watcherExit,
    rejectAfter(600000,'watcher_timeout'),
  ]);
  assert.equal(watcherCode,0);
  const diagnosed=await api('');
  assert.equal(diagnosed.status,200);assert.equal(diagnosed.body.status,'DIAGNOSED');
  assert.ok(['completed','insufficient_evidence'].includes(diagnosed.body.analysis.status));
  assert.match(diagnosed.body.analysis.explanation,/PostgreSQL container.*stopped/);
  summary.diagnosis={status:diagnosed.body.status,reasoning_status:diagnosed.body.analysis.status,
    root_cause:diagnosed.body.analysis.probable_root_cause,
    explanation:diagnosed.body.analysis.explanation,missing:diagnosed.body.analysis.missing_information};
  summary.checks.push('Docker watcher classified and persisted the real ERROR incident',
    'Watcher automatically completed the existing LangGraph/Qwen investigation');
  console.log('Automatic diagnosis persisted; preparing bound proposal.');
  const proposal=await api('/remediation/proposal',{});assert.equal(proposal.status,201);assert.equal(proposal.body.state,'BLOCKED');
  assert.equal((await api('')).body.status,'DIAGNOSED');
  summary.checks.push('Bound proposal persisted BLOCKED before readiness attestation');
  const readiness=await api('/remediation/readiness',{action_id:proposal.body.action_id,
    proposal_fingerprint:proposal.body.action.proposal_fingerprint});
  assert.equal(readiness.status,200);assert.equal(readiness.body.state,'PENDING_APPROVAL');
  assert.deepEqual(readiness.body.readiness.verified_requirements,
    ['health_check_ready','impact_reviewed','rollback_plan_verified','target_scope_reviewed']);
  assert.ok(Object.values(readiness.body.readiness.checks).every(Boolean));
  assert.equal((await api('')).body.status,'PENDING_APPROVAL');
  const beforeApproval=await py("import json; from llm_reasoner.demo_remediation import DemoDockerAdapter; print(json.dumps(DemoDockerAdapter().snapshot()))");assert.equal(beforeApproval.state,'exited');
  const p=readiness.body;summary.proposal_fingerprint=p.action.proposal_fingerprint;
  const decision={action_id:p.action_id,proposal_fingerprint:p.action.proposal_fingerprint,decision:'APPROVED',reviewed:true};
  const stale=await api('/remediation/decision',{...decision,proposal_fingerprint:'0'.repeat(64)});assert.equal(stale.status,409);
  // Authenticated operator decision authorized by the user's explicit demo-test request.
  const resolved=await api('/remediation/decision',decision);assert.equal(resolved.status,200);assert.equal(resolved.body.state,'RESOLVED');
  assert.equal(progressObserved,true);assert.equal((await api('')).body.status,'RESOLVED');
  const health=await fetch('http://127.0.0.1:18080/health');assert.equal(health.status,200);summary.health=await health.json();assert.equal(summary.health.database,'healthy');
  summary.history=resolved.body.history;summary.execution=resolved.body.execution;summary.verification=resolved.body.health;
  const replay=await api('/remediation/decision',decision);assert.equal(replay.status,409);
  summary.checks.push('Bound proposal pending without execution','Stale fingerprint rejected','Authenticated reviewed approval persisted','Controlled Python adapter started existing PostgreSQL','VERIFYING persisted before health I/O','PostgreSQL Docker health and orders-api HTTP 200 verified','RESOLVED persisted','Approval replay rejected');
  // A fresh connection checks persisted state rather than a response/local variable.
  const uri=mongo.getUri('isolated_demo_lifecycle');await mongoose.disconnect();await connectDatabase(uri);
  assert.equal((await api('')).body.status,'RESOLVED');summary.checks.push('RESOLVED survived database reconnect');
  console.log(JSON.stringify(summary,null,2));
} catch(error) {
  console.error(JSON.stringify({error:'demo_lifecycle_failed',type:error.name,code:error.code||null,checks:summary.checks}));
  process.exitCode=1;
} finally {
  if(stopped) {
    // Restore original demo availability on failure; never mark any incident resolved here.
    try {
      const state=await py("import json; from llm_reasoner.demo_remediation import DemoDockerAdapter; print(json.dumps(DemoDockerAdapter().snapshot()))");
      if(state.id===container && state.state==='exited')await exec('docker',['start',container],{timeout:20000});
    }catch{console.error('Demo cleanup needs manual inspection');process.exitCode=1;}
  }
  if(server)await new Promise(resolve=>{
    server.close(resolve);
    server.closeAllConnections();
  });
  if(watcher?.exitCode===null)watcher.kill('SIGTERM');
  await mongoose.disconnect();await mongo?.stop();
}
