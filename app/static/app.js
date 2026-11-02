const $=id=>document.getElementById(id); let history=[];
let charts={};
const fmt=(v,s='')=>v===null||v===undefined?'—':`${Number(v).toFixed(2)}${s}`;
async function loadModels(){
 $('status').textContent='Consultando Ollama…'; $('error').textContent='';
 try{
  const [models,health]=await Promise.all([fetch('/api/models').then(r=>{if(!r.ok)throw Error('Não foi possível listar modelos');return r.json()}),fetch('/api/health').then(r=>r.json())]);
  $('model').innerHTML=models.map(m=>`<option value="${m.name}">${m.name} · ${m.size_gb} GB · ${m.parameter_size||'?'}</option>`).join('');
  $('status').textContent=health.ok?`Ollama conectado (${health.ollama.version})`:'Ollama indisponível';
  if(!models.length)$('status').textContent='Nenhum modelo instalado no Ollama';
 }catch(e){$('status').textContent='Falha na conexão';$('error').textContent=e.message+' — inicie o Ollama e confira a URL.'}
}
function chart(id,label,key,suffix=''){
 if(charts[id])charts[id].destroy();
 charts[id]=new Chart($(id),{type:'bar',data:{labels:history.map(x=>x.model),datasets:[{label,data:history.map(x=>x[key]),borderWidth:1}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:'#dce5f1'}}},scales:{x:{ticks:{color:'#bdc8d7'}},y:{beginAtZero:true,title:{display:true,text:suffix,color:'#bdc8d7'},ticks:{color:'#bdc8d7'}}}}});
}
function renderHistory(){
 $('history').innerHTML=history.map(x=>`<tr><td>${x.model}</td><td>${fmt(x.ttft_s,' s')}</td><td>${fmt(x.tps)}</td><td>${fmt(x.total_s,' s')}</td><td>${fmt(x.ram,' MB')}</td><td>${fmt(x.cpu,'%')}</td><td>${x.tokens??'—'}</td></tr>`).join('')||'<tr><td colspan="7">Nenhum resultado ainda.</td></tr>';
 chart('speedChart','Geração (tokens/s)','tps','tokens/s');chart('ttftChart','TTFT (s)','ttft_s','segundos');
 chart('ramChart','RAM pico (MB)','ram','MB');chart('timeChart','Tempo total (s)','total_s','segundos');
}
$('run').onclick=async()=>{
 if(!$('model').value){$('error').textContent='Instale/seleciona um modelo primeiro.';return}
 $('run').disabled=true;$('error').textContent='';$('status').textContent='Benchmark em execução…';$('output').textContent='Aguardando resposta…';
 try{
  const r=await fetch('/api/benchmark',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:$('model').value,prompt:$('prompt').value,runs:Number($('runs').value),temperature:Number($('temp').value),num_predict:Number($('tokens').value)})});
  const data=await r.json();if(!r.ok)throw Error(data.detail||'Falha no benchmark');
  const a=data.averages, samples=data.runs.flatMap(x=>x.hardware),peakRam=Math.max(0,...samples.map(x=>x.ram_used_mb)),peakCpu=Math.max(0,...samples.map(x=>x.cpu_percent)),peakGpu=Math.max(0,...samples.map(x=>x.gpu.utilization_percent||0));
  const tokenAvg=data.runs.reduce((s,x)=>s+x.output_tokens,0)/data.runs.length;
  const entry={model:data.model,ttft_s:a.ttft_s,tps:a.generation_tokens_per_second,total_s:a.total_time_s,ram:peakRam,cpu:peakCpu,tokens:Math.round(tokenAvg)};
  history.push(entry);renderHistory();
  $('ttft').textContent=fmt(a.ttft_s,' s');$('tps').textContent=fmt(a.generation_tokens_per_second);$('total').textContent=fmt(a.total_time_s,' s');
  $('ram').textContent=fmt(peakRam,' MB');$('cpu').textContent=fmt(peakCpu,'%');$('gpu').textContent=samples.some(x=>x.gpu.available)?fmt(peakGpu,'%'):'N/D';
  $('outtokens').textContent=Math.round(tokenAvg);$('load').textContent=fmt(a.load_time_s,' s');
  $('output').textContent=data.runs[0].output||'(Sem texto retornado)';
  $('status').textContent=`Concluído: ${data.run_count} execução(ões)`;
 }catch(e){$('error').textContent=e.message;$('status').textContent='Benchmark não concluído'}
 finally{$('run').disabled=false}
};
$('refresh').onclick=loadModels;
$('clear').onclick=()=>{history=[];renderHistory()};
$('csv').onclick=()=>{
 if(!history.length)return;
 const cols=['model','ttft_s','tps','total_s','ram','cpu','tokens'];
 const csv=[cols.join(','),...history.map(x=>cols.map(k=>`"${String(x[k]??'').replaceAll('"','""')}"`).join(','))].join('\n');
 const a=document.createElement('a');a.href=URL.createObjectURL(new Blob(['\ufeff'+csv],{type:'text/csv;charset=utf-8'}));a.download='local-llm-bench.csv';a.click();URL.revokeObjectURL(a.href);
};
loadModels();renderHistory();
