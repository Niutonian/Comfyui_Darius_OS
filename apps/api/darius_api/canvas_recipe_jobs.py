"""Shared transaction/preflight path for immutable image and video recipe boards."""
from copy import deepcopy
from secrets import randbelow
from fastapi import HTTPException
from sqlalchemy import select, text
from .canvas_moss import digest
from .database import CanvasGenerationRecord as Generation, CanvasRevisionRecord as Revision

def generate(settings, session_factory, registry, project_id, document_id, payload, adapter):
 from .canvas_api import owned, generation_view
 from .moss_workspace import board_snapshot, owned_board
 from .services import new_id, enqueue_request, register_workflows, add_event
 from .workflows import WorkflowContract, WorkflowInput, WorkflowMapping, WorkflowOutput, RuntimeMapping
 from .atomic_files import atomic_json
 from .canvas_fibo import seed_value
 with session_factory() as session:
  doc=owned(session,project_id,document_id)
  if doc.revision!=payload.revision:raise HTTPException(409,'Refresh the saved board before generating')
  board=board_snapshot(session,project_id,document_id,payload.boardId,payload.boardRevision)
  if not board or board['adapterVersion'] not in adapter.PROFILES:raise HTTPException(422,'Choose a supported recipe board')
  config=adapter.Config.model_validate(board[adapter.CONFIG_FIELD])
  profile=board['adapterVersion']
  if payload.profileId and payload.profileId!=profile:raise HTTPException(409,'Board recipe changed; refresh before generating')
  if payload.promotedFromGenerationId:raise HTTPException(422,'This recipe cannot promote an image preview')
  selection=doc.selection_version; snapshot=deepcopy(session.get(Revision,(doc.id,doc.revision)).content_json)
  seed=seed_value(payload.seed if payload.seed is not None else board.get('seed') if board.get('seed') is not None else randbelow(2**32))
  try:
   # Compile with placeholders first: missing input/prompt errors do not upload or queue.
   adapter.compile_graph(settings,config,seed,{i.id:'pending.png' for i in adapter.active_inputs(config)}, content=snapshot)
   status=adapter.readiness(settings,profile)
   if not status['ready']:raise ValueError('Board setup required: '+'; '.join(status['issues']))
   media,receipts=adapter.upload_inputs(settings,session,project_id,config)
   graph,provenance=adapter.compile_graph(settings,config,seed,media,content=snapshot)
   if adapter.OUTPUT_KIND == 'image':
    size=adapter.output_size(config.activeProfile,config.drafts[config.activeProfile],receipts[0] if receipts else None)
    provenance.update(width=size[0] if size else None,height=size[1] if size else None)
  except Exception as exc:raise HTTPException(422,str(exc)+'. Draft retained; no render queued.') from exc
 generation_id=new_id();workflow_id='canvas-'+generation_id
 path=settings.workflow_definitions_dir/'graphs'/(workflow_id+'.json');atomic_json(path,graph)
 from .providers import ComfyMcpProvider
 try:
  validation=ComfyMcpProvider(settings).validate_api_graph(path,graph,timeout=60)
  if validation.get('valid') is not True or validation.get('errors'):raise ValueError(str(validation.get('errors') or 'Recipe graph validation failed'))
 except Exception as exc:raise HTTPException(422,str(exc)+'. Board draft retained; no render queued.') from exc

 contract=WorkflowContract(id=workflow_id,name=snapshot['name']+' · '+adapter.OUTPUT_KIND.title(),version=profile,capability=provenance.get('capability','image-to-video'),execution_provider='local-comfyui',workflow_reference=str(path.resolve()),
  required_inputs=[WorkflowInput(key='seed',type='integer',default=seed,maps_to=WorkflowMapping(slot=provenance.get('seedSlot',provenance['sampler']+'.noise_seed')))],output=WorkflowOutput(kind=adapter.OUTPUT_KIND,count=len(provenance['outputs'])),runtime_mapping=RuntimeMapping(filename_prefix_slot=provenance['outputNode']+'.filename_prefix',api_format=True),
  output_node_ids=list(provenance['outputs']),source_asset_ids=[r['assetId'] for r in receipts],internal_only=True,project_id=project_id,requires_approval=True)
 atomic_json(settings.workflow_definitions_dir/(workflow_id+'.json'),contract.model_dump());registry.load();register_workflows(session_factory,registry,workflow_ids=[workflow_id])
 with session_factory.begin() as session:
  session.execute(text('BEGIN IMMEDIATE'));doc=owned(session,project_id,document_id)
  existing=session.scalar(select(Generation).where(Generation.document_id==doc.id,Generation.idempotency_key==payload.idempotencyKey))
  if existing:return generation_view(session,existing)
  current=owned_board(session,project_id,board['boardId'])
  if current.revision!=board['boardRevision'] or doc.revision!=payload.revision:raise HTTPException(409,'Board changed during preparation; generate the saved draft again')
  adapter.validate_inputs(session,project_id,config)
  job=enqueue_request(session_factory,registry,project_id,workflow_id,provenance['conditioningPrompt'],{'seed':seed},True,_session=session,allow_internal=True)
  provenance.update(board=board,documentSnapshot=snapshot,mediaReceipts=receipts,projectId=project_id,documentId=document_id,documentRevision=payload.revision,generationId=generation_id)
  job.input_payload={**job.input_payload,'canvas_generation_id':generation_id,'canvas_document_id':document_id,'canvas_revision':payload.revision,'canvas_graph_digest':digest(graph),'canvas_contract_digest':digest(contract.model_dump(mode='json')),'canvas_board_id':board['boardId'],'worker_ready':True,'render_name':snapshot['name']+' · '+provenance.get('profileName',adapter.active_profile_name(config))}
  session.add(Generation(id=generation_id,document_id=document_id,project_id=project_id,revision=payload.revision,job_id=job.id,idempotency_key=payload.idempotencyKey,seed=seed,selection_version=selection,provenance_json=provenance));session.flush()
  add_event(session,project_id,'canvas.queued','canvas',document_id,{'job_id':job.id,'mode':adapter.active_profile_name(config)});receipt=generation_view(session,session.get(Generation,generation_id))
 from .local_render import launch_local_job
 try:launch_local_job(settings,receipt['jobId'])
 except OSError:receipt['launchError']='Saved to queue; start the worker from Canvas.'
 return receipt
