// Bounded conversion of ONE cached section boundary to declarative XY points.
// No geometry rebuild, offset, upload, CAD mutation or provider request.
export function sectionProfile(data, {revision, section_id, part, region_index=0, boundary='outer', hole_index=0, tolerance=0.02, max_points=512}) {
 if(data.revision!==revision||data.units!=='mm')throw new Error('Section identity/units mismatch');
 if(!Number.isFinite(tolerance)||tolerance<0.005||tolerance>0.5||!Number.isInteger(max_points)||max_points<3||max_points>512)throw new Error('Invalid profile tolerance/point bound');
 if(!Number.isInteger(region_index)||region_index<0||!Number.isInteger(hole_index)||hole_index<0||!['outer','hole'].includes(boundary))throw new Error('Invalid boundary selector');
 const regions=(data.regions??[]).filter(r=>r.part===part),region=regions[region_index];
 if(!region)throw new Error('Unknown part/region or empty section');
 const points=boundary==='outer'?region.outer:region.holes?.[hole_index];
 if(!Array.isArray(points)||points.length<4||points.length>8192||points.some(p=>!Array.isArray(p)||p.length!==2||p.some(x=>!Number.isFinite(x)||Math.abs(x)>20000)))throw new Error('Expected a finite closed boundary with at most 8192 input points');
 const distance=(p,a,b)=>{const dx=b[0]-a[0],dy=b[1]-a[1],d=dx*dx+dy*dy;const t=d?Math.max(0,Math.min(1,((p[0]-a[0])*dx+(p[1]-a[1])*dy)/d)):0;return Math.hypot(p[0]-a[0]-t*dx,p[1]-a[1]-t*dy);};
 if(Math.hypot(points[0][0]-points.at(-1)[0],points[0][1]-points.at(-1)[1])>1e-8)throw new Error('Section boundary is not closed');
 const keep=new Set([0,points.length-1]),stack=[[0,points.length-1]];let error=0;
 while(stack.length){const [a,b]=stack.pop();let far=0,index=-1;for(let i=a+1;i<b;i++){const d=distance(points[i],points[a],points[b]);if(d>far){far=d;index=i;}}
  if(far>tolerance&&index>=0){keep.add(index);stack.push([a,index],[index,b]);}else error=Math.max(error,far);
 }
 const output=[...keep].sort((a,b)=>a-b).slice(0,-1).map(i=>[...points[i]]);
 if(output.length<3||output.length>max_points)throw new Error(`Profile needs ${output.length} points at this tolerance (limit ${max_points}); change tolerance explicitly, never silently coarsen`);
 const cross=(a,b,c)=>(b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0]);
 const on=(p,a,b)=>Math.abs(cross(a,b,p))<1e-9&&p[0]>=Math.min(a[0],b[0])-1e-9&&p[0]<=Math.max(a[0],b[0])+1e-9&&p[1]>=Math.min(a[1],b[1])-1e-9&&p[1]<=Math.max(a[1],b[1])+1e-9;
 for(let i=0;i<output.length;i++)for(let j=i+1;j<output.length;j++){
  if(j===i+1||(i===0&&j===output.length-1))continue;
  const a=output[i],b=output[(i+1)%output.length],c=output[j],d=output[(j+1)%output.length];
  if((cross(a,b,c)*cross(a,b,d)<0&&cross(c,d,a)*cross(c,d,b)<0)||on(a,c,d)||on(b,c,d)||on(c,a,b)||on(d,a,b))throw new Error('Simplification creates a touching/self-intersecting profile; use a smaller tolerance');
 }
 let area=output.reduce((sum,a,i)=>{const b=output[(i+1)%output.length];return sum+a[0]*b[1]-a[1]*b[0];},0)/2;
 if(Math.abs(area)<1e-8)throw new Error('Degenerate section profile');
 if(area<0)output.reverse();
 return {revision,section_id,part,region_index,boundary,hole_index:boundary==='hole'?hole_index:null,units:'mm',plane:data.plane,source_basis:data.basis,representation:data.representation??'step',points:output,point_count:output.length,source_points:points.length-1,area_mm2:Math.abs(area),simplification_error_bound_mm:error,tolerance_mm:tolerance,
  other_boundaries_omitted:region.holes?.length??0,
  use:'Points are local UV coordinates for extrude_z, NOT world XYZ. Output is CCW without repeated closing vertex. This selects one boundary only; explicitly handle any other boundaries. No clearance/kerf/shrinkage offset. Source tessellation/sampling error remains additional to the simplification bound.'};
}
