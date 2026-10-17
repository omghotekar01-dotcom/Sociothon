import assert from 'node:assert/strict';
import test from 'node:test';
import {guideRequest,reportPath} from '../apps/web/src/startGuide.ts';
test('report shortcuts open a real report form with the relevant service selected',()=>{
 assert.equal(guideRequest('report a water leak').path,'/report?domain=water');
 assert.equal(guideRequest('add case for broken streetlight').path,'/report?domain=streetlights');
 assert.equal(guideRequest('file a pothole complaint').path,'/report?domain=roads');
 assert.equal(reportPath('something-else'),'/report');
});
test('tracking must outrank creating another duplicate issue',()=>{
 assert.equal(guideRequest('track my case water leak').path,'/reports');
 assert.equal(guideRequest('check my report status').path,'/reports');
});
test('demo and service exploration have exact working destinations',()=>{
 assert.equal(guideRequest('open live demo').path,'/demo');
 assert.equal(guideRequest('electricity signals').path,'/domains/electricity');
 assert.equal(guideRequest('open dashboard').path,'/overview');
});
test('the guide never promises AI case submission',()=>{
 assert.match(guideRequest('new water complaint').detail,/Nothing has been sent yet/);
});
