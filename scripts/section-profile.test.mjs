import test from 'node:test';
import assert from 'node:assert/strict';
import {sectionProfile} from '../.pi/extensions/lib/section-profile.mjs';
const revision='a'.repeat(32),section_id='b'.repeat(64);
const ring=(r,n=720)=>Array.from({length:n+1},(_,i)=>[r*Math.cos(2*Math.PI*(i%n)/n),r*Math.sin(2*Math.PI*(i%n)/n)]);
const data={revision,units:'mm',representation:'mesh',basis:'approximate mesh',plane:{origin:[0,0,20],u:[1,0,0],v:[0,1,0],normal:[0,0,1]},regions:[{part:'part',outer:ring(10),holes:[ring(4)]}]};
const params={revision,section_id,part:'part'};
test('bounded CCW profile, explicit single boundary and additional error only',()=>{
 const p=sectionProfile(data,params);
 assert.ok(p.point_count<512&&p.point_count>32);assert.ok(p.simplification_error_bound_mm<=.02);
 assert.equal(p.other_boundaries_omitted,1);assert.equal(p.representation,'mesh');assert.equal(p.plane.origin[2],20);
 assert.notDeepEqual(p.points[0],p.points.at(-1));
 assert.ok(p.area_mm2>310&&p.area_mm2<315);
 const hole=sectionProfile(data,{...params,boundary:'hole'});assert.ok(hole.area_mm2<51);
 assert.deepEqual(data.regions[0].outer,ring(10));
});
test('reject identity, units, bounds, invalid loops and silent coarsening',()=>{
 for(const [d,p] of [[{...data,revision:'wrong'},params],[{...data,units:'inches'},params],[data,{...params,part:'missing'}],[data,{...params,tolerance:NaN}],[data,{...params,max_points:4}],[data,{...params,boundary:'hole',hole_index:10}]])assert.throws(()=>sectionProfile(d,p));
 for(const outer of [[[0,0],[1,0],[1,1],[0,1]],[[0,0],[1,1],[0,1],[1,0],[0,0]],[[0,0],[NaN,0],[1,1],[0,0]],ring(10,8192)])assert.throws(()=>sectionProfile({...data,regions:[{part:'part',outer,holes:[]}]},params));
});
