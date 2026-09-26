import { test, after } from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { createServer } from 'vite';
const server = await createServer({ server: { middlewareMode: true }, appType: 'custom' });
after(() => server.close());
const { default: Panel } = await server.ssrLoadModule('/src/components/RemediationPanel.jsx');
const { remediationNotification } = await server.ssrLoadModule('/src/components/RemediationPanel.jsx');
const { default: BackendStatus } = await server.ssrLoadModule('/src/components/BackendStatus.jsx');
const { Toast } = await server.ssrLoadModule('/src/components/Toast.jsx');
const incident = { incident_id:'INC-DEMO-001',service:'orders-api',status:'DIAGNOSED',analysis:{} };
const render = changes => renderToStaticMarkup(React.createElement(Panel,{incident:{...incident,...changes}}));
test('diagnosed incident offers authenticated proposal, not direct execution',()=>{
  const html=render({});assert.match(html,/Prepare recovery proposal/);assert.match(html,/type="password"/);
  assert.doesNotMatch(html,/Approve and recover/);assert.match(html,/<button disabled="">Prepare/);
});
test('pending proposal shows review and disabled approval/rejection until review and token',()=>{
  const html=render({remediation:{state:'PENDING_APPROVAL',action_id:'a',action:{proposal_fingerprint:'f'.repeat(64)},proposal:{description:'Reviewed container'},plan:{impact:'Retain data'}}});
  assert.match(html,/Reviewed container/);assert.match(html,/Retain data/);
  assert.match(html,/<button disabled="">Approve and recover/);assert.match(html,/<button disabled="">Reject/);
  assert.match(html,/type="checkbox"/);
});
test('blocked proposal offers authenticated readiness retry and shows concrete checks',()=>{
  const html=render({remediation:{state:'BLOCKED',action_id:'a',
    action:{proposal_fingerprint:'f'.repeat(64)},readiness:{checks:{
      target_scope_reviewed:true,health_check_ready:false}}}});
  assert.match(html,/Verify readiness again/);assert.match(html,/target_scope_reviewed:.*verified/);
  assert.match(html,/health_check_ready:.*not verified/);assert.doesNotMatch(html,/Approve and recover/);
});
test('verifying and resolved states expose health without replay controls',()=>{
  assert.match(render({remediation:{state:'VERIFYING'}}),/Use Refresh/);
  const html=render({remediation:{state:'RESOLVED',health:{status:'healthy',details:'orders-api verified'}}});
  assert.match(html,/orders-api verified/);assert.doesNotMatch(html,/Approve and recover|Prepare recovery proposal/);
});
test('failed and rejected attempts have no execution controls',()=>{
  for(const state of ['FAILED','REJECTED'])assert.doesNotMatch(render({remediation:{state}}),/Approve and recover|Prepare recovery proposal/);
});
test('out of scope incidents do not get remediation controls',()=>{
  assert.equal(render({service:'other'}),'');assert.equal(render({incident_id:'OTHER'}),'');
});
test('approval API sends only the bound decision to backend',async()=>{
  const { remediationRequest }=await server.ssrLoadModule('/src/services/api.js');
  const original=globalThis.fetch;let call;
  globalThis.fetch=async(...args)=>{call=args;return {ok:true,json:async()=>({state:'REJECTED'})};};
  try {
    const body={action_id:'a',proposal_fingerprint:'f'.repeat(64),decision:'REJECTED',reviewed:true};
    await remediationRequest('INC-DEMO-001','decision','test-only-token',body);
    assert.match(call[0],/\/api\/incidents\/INC-DEMO-001\/remediation\/decision$/);
    assert.equal(call[1].method,'POST');assert.deepEqual(JSON.parse(call[1].body),body);
    assert.equal(call[1].headers.Authorization,'Bearer test-only-token');
  }finally{globalThis.fetch=original;}
});
test('health API uses the existing backend health endpoint',async()=>{
  const { getHealth }=await server.ssrLoadModule('/src/services/api.js');
  const original=globalThis.fetch;let target;
  globalThis.fetch=async url=>{target=url;return {ok:true,json:async()=>({status:'healthy',backend:'up',database:'connected'})};};
  try {
    assert.deepEqual(await getHealth(),{status:'healthy',backend:'up',database:'connected'});
    assert.match(target,/\/health$/);
  }finally{globalThis.fetch=original;}
});
test('backend status renders checking, online and offline states',()=>{
  const renderStatus=online=>renderToStaticMarkup(React.createElement(BackendStatus,{online}));
  assert.match(renderStatus(null),/Checking backend/);
  assert.match(renderStatus(true),/backend-online.*Backend online/);
  assert.match(renderStatus(false),/backend-offline.*Backend offline/);
});
test('toast is accessible and remediation outcomes map to useful notifications',()=>{
  const html=renderToStaticMarkup(React.createElement(Toast,{id:1,message:'Saved',tone:'success',onDismiss:()=>{}}));
  assert.match(html,/role="status"/);assert.match(html,/Dismiss notification/);assert.match(html,/Saved/);
  assert.deepEqual(remediationNotification('PENDING_APPROVAL'),['Recovery proposal is ready for human approval.','success']);
  assert.deepEqual(remediationNotification('BLOCKED'),['Readiness checks remain incomplete.','warning']);
  assert.deepEqual(remediationNotification('RESOLVED'),['PostgreSQL recovery verified; incident resolved.','success']);
});
