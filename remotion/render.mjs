// Separate Node process. Never imports the Python/CapCut packages.
import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {bundle} from '@remotion/bundler';
import {selectComposition,renderMedia} from '@remotion/renderer';
const request=JSON.parse(await fs.readFile(process.argv[2],'utf8'));
const receipt=process.argv[3],root=path.dirname(fileURLToPath(import.meta.url));
const output=request.output_dir,lock=path.join(output,'remotion.lock');
const atomic=async(file,value)=>{await fs.writeFile(file+'.tmp',JSON.stringify(value));await fs.rename(file+'.tmp',file);};
let owned=false;
try{
  // Reconnect to a previous render after a server restart or timeout.
  while(!owned){
    try{if(JSON.parse(await fs.readFile(receipt,'utf8')).status==='completed')process.exit(0);}catch{}
    try{await fs.mkdir(lock);owned=true;await fs.writeFile(path.join(lock,'pid'),String(process.pid));}
    catch(error){
      if(error.code!=='EEXIST')throw error;
      let alive=true;
      try{const pid=Number(await fs.readFile(path.join(lock,'pid'),'utf8'));if(!pid)throw Error('invalid pid');process.kill(pid,0);}
      catch(error){
        if(error.code==='ESRCH')alive=false;
        else{const info=await fs.stat(lock);if(Date.now()-info.mtimeMs>30000)alive=false;}
      }
      if(!alive){await fs.rm(lock,{recursive:true,force:true});continue;}
      await new Promise(resolve=>setTimeout(resolve,1000));
    }
  }
  const serveUrl=await bundle({entryPoint:path.join(root,'root.jsx'),outDir:path.join(output,'bundle')});
  // The renderer serves only this job's clean video from its local static directory.
  await fs.mkdir(path.join(output,'bundle','public'),{recursive:true});
  await fs.copyFile(request.source,path.join(output,'bundle','public','source.mp4'));
  const props={source:'/public/source.mp4',duration:request.duration,document:request.document};
  const composition=await selectComposition({serveUrl,id:'InstaOverlay',inputProps:props});
  const target=path.join(output,'remotion-final.mp4');
  await renderMedia({serveUrl,composition,inputProps:props,codec:'h264',audioCodec:'aac',pixelFormat:'yuv420p',
    outputLocation:target+'.partial.mp4',concurrency:2,overwrite:true});
  await fs.rename(target+'.partial.mp4',target);
  await atomic(receipt,{status:'completed',export_path:target});
}catch(error){await atomic(receipt,{status:'error',error:String(error.stack||error)});process.exitCode=1;}
finally{if(owned)await fs.rm(lock,{recursive:true,force:true});}
