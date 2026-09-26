import { test, before, after, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { randomBytes } from "node:crypto";
import request from "supertest";
import mongoose from "mongoose";
import { MongoMemoryServer } from "mongodb-memory-server";
import { createApp } from "../src/app.js";
import { connectDatabase } from "../src/config/database.js";
import { Incident } from "../src/models/Incident.js";
const token = randomBytes(32).toString('hex');
const fingerprint = 'f'.repeat(64);
let mongo, app, calls, outcome;
const record = {incident_id:'INC-DEMO-001',timestamp:'2026-09-25T10:00:00Z',service:'orders-api',message:'Database unavailable',log_level:'error',classification:'ERROR',status:'DIAGNOSED',analysis:{incident_id:'INC-DEMO-001'}};
const worker = async (payload, onProgress) => {
  calls.push(payload);
  if(payload.operation==='execute' && outcome==='throw') throw new Error('private detail');
  const proposal=payload.proposal || {action_id:payload.action_id,incident_id:'INC-DEMO-001',service:'postgres',action_type:'restart_service',parameters:{},description:'Reviewed demo recovery'};
  const executing=payload.operation==='execute';
  const checking=payload.operation==='readiness';
  if(executing && outcome!=='missing-progress') {
    await onProgress({event:'VERIFYING',action_id:proposal.action_id});
    assert.equal((await Incident.findOne()).status,'VERIFYING');
  }
  const readyChecks={target_scope_reviewed:outcome!=='partial-readiness',impact_reviewed:true,
    rollback_plan_verified:true,health_check_ready:outcome!=='partial-readiness'};
  const verified=['health_check_ready','impact_reviewed','rollback_plan_verified','target_scope_reviewed'].filter(name=>readyChecks[name]);
  const missing=['health_check_ready','impact_reviewed','rollback_plan_verified','target_scope_reviewed'].filter(name=>!readyChecks[name]);
  const eligible=(checking || executing) && !missing.length;
  return {proposal,action:{proposal_fingerprint:fingerprint,approval_eligible:eligible,executable:false,missing_requirements:missing},
    state:executing?'RESOLVED':checking&&eligible?'PENDING_APPROVAL':'BLOCKED',
    history:executing?['DIAGNOSED','PROPOSED','BLOCKED','PENDING_APPROVAL','APPROVED','EXECUTING','VERIFYING','RESOLVED']:
      checking?['DIAGNOSED','PROPOSED','BLOCKED','PENDING_APPROVAL']:['DIAGNOSED','PROPOSED','BLOCKED'],
    execution:executing?{status:'succeeded',action_id:proposal.action_id,service:'postgres'}:null,
    health:executing?{service:'postgres',status:outcome==='unhealthy'?'unhealthy':'healthy',details:'Checked'}:null,
    plan:{action:'Start the stopped demo container'},
    readiness:(checking||executing)?{checks:readyChecks,verified_requirements:verified}:null};
};
const post = (path,body,auth=true,target=app) => {
  const req=request(target).post(`/api/incidents/INC-DEMO-001/remediation/${path}`);
  if(auth)req.set('Authorization',`Bearer ${token}`);
  return req.send(body);
};
const propose=async()=>{const r=await post('proposal',{});assert.equal(r.status,201);return r.body;};
const readiness=async p=>{const r=await post('readiness',{action_id:p.action_id,proposal_fingerprint:fingerprint});assert.equal(r.status,200);return r.body;};
const prepare=async()=>readiness(await propose());
const decision=(p,choice='APPROVED')=>({action_id:p.action_id,proposal_fingerprint:fingerprint,decision:choice,reviewed:true});
before(async()=>{mongo=await MongoMemoryServer.create();await connectDatabase(mongo.getUri('remediation_test'));});
after(async()=>{await mongoose.disconnect();await mongo?.stop();});
beforeEach(async()=>{await Incident.deleteMany({});await Incident.create(record);calls=[];outcome='healthy';app=createApp({remediation:{worker,operatorToken:token}});});

test('proposal requires authenticated operator and trusted origin',async()=>{
  assert.equal((await post('proposal',{},false)).status,401);
  assert.equal((await post('proposal',{}).set('Origin','https://untrusted.example')).status,403);
  assert.equal(calls.length,0);
});
test('unconfigured operator disables mutations',async()=>{
  const target=createApp({remediation:{worker,operatorToken:''}});
  assert.equal((await post('proposal',{},true,target)).status,503);
});
test('model flags and arbitrary parameters cannot create actions',async()=>{
  assert.equal((await post('proposal',{executable:true})).status,400);
  assert.equal(calls.length,0);
});
test('proposal persists blocked state and never executes',async()=>{
  const p=await propose();assert.equal(p.state,'BLOCKED');assert.equal(calls.length,1);
  assert.equal(calls[0].operation,'prepare');assert.equal((await Incident.findOne()).status,'DIAGNOSED');
  assert.equal((await request(app).get('/api/incidents/INC-DEMO-001/remediation')).body.action_id,p.action_id);
});
test('readiness verifies the bound proposal and persists pending approval',async()=>{
  const p=await propose();const ready=await readiness(p);
  assert.equal(ready.state,'PENDING_APPROVAL');assert.equal(calls[1].operation,'readiness');
  assert.equal(calls[1].proposal.action_id,p.action_id);
  assert.equal((await Incident.findOne()).status,'PENDING_APPROVAL');
});
test('readiness safely restores Mongo-minimized empty restart parameters',async()=>{
  const p=await propose();
  await Incident.updateOne({incident_id:record.incident_id},
    {$unset:{'remediation.proposal.parameters':1,'remediation.action.parameters':1}});
  const ready=await readiness(p);
  assert.deepEqual(calls[1].proposal.parameters,{});
  assert.deepEqual(ready.proposal.parameters,{});
  assert.deepEqual((await Incident.findOne()).remediation.proposal.parameters,{});
});
test('readiness persists blocked and attests only verified requirements',async()=>{
  const p=await propose();outcome='partial-readiness';const checked=await readiness(p);
  assert.equal(checked.state,'BLOCKED');assert.deepEqual(checked.readiness.verified_requirements,
    ['impact_reviewed','rollback_plan_verified']);
  assert.deepEqual(checked.action.missing_requirements,
    ['health_check_ready','target_scope_reviewed']);
  assert.equal((await Incident.findOne()).status,'DIAGNOSED');
});
test('duplicate concurrent proposals reserve once',async()=>{
  const results=await Promise.all([post('proposal',{}),post('proposal',{})]);
  assert.deepEqual(results.map(r=>r.status).sort(),[201,409]);assert.equal(calls.length,1);
});
test('approval executes once and only verified success resolves',async()=>{
  const p=await prepare();const r=await post('decision',decision(p));assert.equal(r.status,200);
  assert.equal(r.body.state,'RESOLVED');assert.equal((await Incident.findOne()).status,'RESOLVED');
  assert.equal(calls[2].decision.actor,'demo-operator');assert.equal(calls[2].operation,'execute');
  assert.equal((await post('decision',decision(p))).status,409);assert.equal(calls.length,3);
});
test('rejection is terminal without spawning executor',async()=>{
  const p=await prepare();const r=await post('decision',decision(p,'REJECTED'));
  assert.equal(r.body.state,'REJECTED');assert.equal(calls.length,2);
  assert.equal((await Incident.findOne()).status,'DIAGNOSED');
  assert.equal((await post('decision',decision(p))).status,409);
});
test('stale fingerprints, actor injection and missing review cannot execute',async()=>{
  const p=await prepare();
  assert.equal((await post('decision',{...decision(p),proposal_fingerprint:'0'.repeat(64)})).status,409);
  assert.equal((await post('decision',{...decision(p),actor:'model'})).status,400);
  assert.equal((await post('decision',{...decision(p),reviewed:false})).status,400);
  assert.equal(calls.length,2);
});
test('concurrent approval/rejection is one durable decision',async()=>{
  const p=await prepare();const rs=await Promise.all([post('decision',decision(p)),post('decision',decision(p,'REJECTED'))]);
  assert.deepEqual(rs.map(r=>r.status).sort(),[200,409]);assert.ok(calls.length<=3);
});
test('unhealthy verification overrides claimed RESOLVED',async()=>{
  const p=await prepare();outcome='unhealthy';const r=await post('decision',decision(p));
  assert.equal(r.body.state,'FAILED');assert.equal((await Incident.findOne()).status,'FAILED');
});
test('timeout/uncertain execution remains consumed across app restart',async()=>{
  const p=await prepare();outcome='throw';const r=await post('decision',decision(p));
  assert.equal(r.status,502);assert.ok(!JSON.stringify(r.body).includes('private detail'));
  app=createApp({remediation:{worker,operatorToken:token}});
  assert.equal((await post('decision',decision(p))).status,409);assert.equal(calls.length,3);
  assert.equal((await post('proposal',{})).status,409);
});
test('legacy endpoints cannot forge resolution or alter managed analysis/status',async()=>{
  assert.equal((await request(app).patch('/api/incidents/INC-DEMO-001/status').send({status:'RESOLVED'})).status,409);
  await prepare();
  assert.equal((await request(app).patch('/api/incidents/INC-DEMO-001/status').send({status:'DIAGNOSED'})).status,409);
  const valid={incident_id:'INC-DEMO-001',status:'insufficient_evidence',probable_root_cause:null,explanation:'Observation',references:[],remediation_steps:[],configuration_changes:[],missing_information:[]};
  assert.equal((await request(app).patch('/api/incidents/INC-DEMO-001/analysis').send(valid)).status,409);
  assert.equal(calls.length,2);
});
test('incident creation cannot claim verified resolution',async()=>{
  assert.equal((await request(app).post('/api/incidents').send({...record,incident_id:'INC-NEW',status:'RESOLVED',analysis:null})).status,409);
});
test('persisted EXECUTING reservation after crash cannot replay',async()=>{
  const p=await prepare();await Incident.updateOne({incident_id:record.incident_id},{$set:{'remediation.state':'EXECUTING','remediation.attempt_reserved':true,status:'REMEDIATING'}});
  app=createApp({remediation:{worker,operatorToken:token}});
  assert.equal((await post('decision',decision(p))).status,409);assert.equal(calls.length,2);
});

test('worker cannot resolve without persisting VERIFYING',async()=>{
  const p=await prepare();outcome='missing-progress';
  const r=await post('decision',decision(p));
  assert.equal(r.body.state,'FAILED');assert.equal((await Incident.findOne()).status,'FAILED');
});
test('persisted VERIFYING after crash cannot replay',async()=>{
  const p=await prepare();await Incident.updateOne({incident_id:record.incident_id},{$set:{'remediation.state':'VERIFYING','remediation.attempt_reserved':true,status:'VERIFYING'}});
  app=createApp({remediation:{worker,operatorToken:token}});
  assert.equal((await post('decision',decision(p))).status,409);assert.equal(calls.length,2);
});
