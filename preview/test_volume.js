'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),V=require('./volume');
test('front eyes visible, rear hidden, side far eye occluded',()=>{assert.ok(V.geometry(0).eyes.every(Boolean));assert.deepEqual(V.geometry(0,{yaw:Math.PI}).eyes,['','']);assert.equal(V.geometry(0,{yaw:Math.PI/2}).eyes.filter(Boolean).length,1);});
test('projected contour changes under yaw and pitch, finite closed paths',()=>{for(let i=0;i<3;i++){const front=V.geometry(i);assert.notEqual(front.body,V.geometry(i,{yaw:.7}).body);for(let y=-3;y<3;y+=.1){const g=V.geometry(i,{yaw:y,pitch:.3,roll:.2});assert.ok(!JSON.stringify(g).match(/NaN|Infinity/));assert.equal(g.contour.length,96);}}});
test('eye width foreshortens and gets partially clipped continuously',()=>{const widths=[0,.6,1.1].map(y=>V.geometry(0,{yaw:y}).eyePoints[1]).map(p=>p.length?Math.max(...p.map(x=>x[0]))-Math.min(...p.map(x=>x[0])):0);assert.ok(widths[0]>widths[1]&&widths[1]>widths[2]);});
test('rotation preserves vector length',()=>{assert.ok(Math.abs(Math.hypot(...V.rotate([1,2,3],{yaw:1,pitch:2,roll:3}))-Math.sqrt(14))<1e-12);});
