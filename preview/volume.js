'use strict';
// Original analytic geometry. No third-party coordinates, shaders or assets.
const VolumeAvatar = (() => {
 const NS='http://www.w3.org/2000/svg';
 const radii=[[22,24,19],[25,21,18],[21,25,17]];
 function rotate(p, pose={}) {
  const {yaw=0,pitch=0,roll=0}=pose;
  const [x,y,z]=p, a=x*Math.cos(yaw)+z*Math.sin(yaw), b=-x*Math.sin(yaw)+z*Math.cos(yaw);
  const c=y*Math.cos(pitch)-b*Math.sin(pitch), d=y*Math.sin(pitch)+b*Math.cos(pitch);
  return [a*Math.cos(roll)-c*Math.sin(roll),a*Math.sin(roll)+c*Math.cos(roll),d];
 }
 const path=points=>points.length?'M'+points.map(p=>`${(32+p[0]).toFixed(3)},${(32+p[1]).toFixed(3)}`).join('L')+'Z':'';
 function geometry(variant=0,pose={},openness=1) {
  const r=radii[variant%3], basis=r.map((v,i)=>rotate([i===0?v:0,i===1?v:0,i===2?v:0],pose));
  const contour=[];
  // Orthographic silhouette: support points of the projected quadratic form.
  for(let i=0;i<96;i++) {
   const t=i*Math.PI/48, n=[Math.cos(t),Math.sin(t)], dots=basis.map(b=>b[0]*n[0]+b[1]*n[1]);
   const length=Math.hypot(...dots);
   contour.push([basis.reduce((s,b,j)=>s+b[0]*dots[j],0)/length,basis.reduce((s,b,j)=>s+b[1]*dots[j],0)/length]);
  }
  const eyes=[-1,1].map(side=>{
   const ring=[];
   for(let i=0;i<64;i++) {
    const t=i*Math.PI/32, x=side*7+2.25*Math.cos(t), y=-1+5.2*Math.max(.08,openness)*Math.sin(t);
    const z=r[2]*Math.sqrt(Math.max(0,1-(x/r[0])**2-(y/r[1])**2));
    ring.push({p:rotate([x,y,z],pose), visibility:rotate([x/r[0]**2,y/r[1]**2,z/r[2]**2],pose)[2]});
   }
   // Clip at the actual surface tangent, including partial eye visibility.
   const points=[];
   ring.forEach((a,i)=>{const b=ring[(i+1)%ring.length]; if(a.visibility>=0) points.push(a.p);
    if((a.visibility>=0)!==(b.visibility>=0)){const f=a.visibility/(a.visibility-b.visibility);points.push(a.p.map((v,j)=>v+(b.p[j]-v)*f));}
   });
   return points;
  });
  return {body:path(contour),eyes:eyes.map(path),eyePoints:eyes,contour};
 }
 function node(tag,attrs={}){const n=document.createElementNS(NS,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));return n;}
 let serial=0;
 function create({variant=0,color='#6e9f90',size=128,pose={},volume=true}={}) {
  const svg=node('svg',{viewBox:'0 0 64 64',width:size,height:size,'aria-hidden':'true'}), id=`volume-${++serial}`;
  const defs=node('defs'), grad=node('radialGradient',{id,cx:'29%',cy:'20%',r:'85%',fx:'29%',fy:'20%'});
  [[0,'#ffffff',.34],[.40,'#ffffff',.04],[.72,'#081f27',.14],[1,'#07151c',.64]].forEach(([offset,color,opacity])=>grad.append(node('stop',{offset,'stop-color':color,'stop-opacity':opacity})));
  defs.append(grad);svg.append(defs);
  const body=node('path',{fill:color}), shade=node('path',{fill:`url(#${id})`}), eyes=[node('path',{fill:'#fafdfc'}),node('path',{fill:'#fafdfc'})];
  svg.append(body,shade,...eyes);shade.style.display=volume?'':'none';
  const draw=(next=pose,open=1)=>{const g=geometry(variant,next,open);body.setAttribute('d',g.body);shade.setAttribute('d',g.body);eyes.forEach((n,i)=>n.setAttribute('d',g.eyes[i]));};draw();
  return {svg,draw};
 }
 return {rotate,geometry,create};
})();
if(typeof module!=='undefined')module.exports=VolumeAvatar;
