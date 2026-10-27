"use client";
import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArrowUpRight, BookmarkPlus, Copy, Lightbulb, RotateCcw, X } from "lucide-react";
import { ideasApi, type CreativeIdea, type IdeaInput } from "@/lib/creative-ideas";
import { subscribeProjectRefresh } from "@/lib/project-sync";
import { rememberWorkspaceValue } from "@/lib/workspace-session";
import { useDariusStore } from "@/lib/store";

export function SaveIdea({ projectId, messageId, text }: {projectId:string; messageId:string; text:string}) {
  const [open,setOpen]=useState(false);
  return <><button type="button" className="secondary-button" onClick={()=>setOpen(true)}><BookmarkPlus size={14}/>Save idea</button>{open ? <SaveIdeaDialog projectId={projectId} messageId={messageId} sourceText={text} onClose={()=>setOpen(false)}/> : null}</>;
}

export function SaveIdeaDialog({projectId,messageId,sourceText,onClose}:{projectId:string;messageId:string;sourceText:string;onClose:()=>void}) {
  const dialog=useRef<HTMLDialogElement>(null), heading=useId(), client=useQueryClient();
  const [title,setTitle]=useState(sourceText.replace(/[`#*]/g,"").trim().split(/\s+/).slice(0,8).join(" ").slice(0,160));
  const [content,setContent]=useState(sourceText),[busy,setBusy]=useState(false),[error,setError]=useState(""),[saved,setSaved]=useState<CreativeIdea|null>(null);
  const pending=useRef<IdeaInput|null>(null);
  useEffect(()=>{const node=dialog.current,previous=document.activeElement as HTMLElement|null;node?.showModal();return()=>{node?.close();previous?.focus?.();};},[]);
  async function save() {
    if(busy)return;setBusy(true);setError("");
    const input={title,content,sourceMessageId:messageId,sourceText};
    const old=pending.current;
    const body=old && JSON.stringify({...old,id:undefined})===JSON.stringify(input) ? old : {...input,id:crypto.randomUUID()};
    pending.current=body;
    try {setSaved(await ideasApi.save(projectId,body));await client.invalidateQueries({queryKey:["creative-ideas",projectId]});}
    catch(err){setError((err as Error).message);}finally{setBusy(false);}
  }
  function openIdeas(){if(useDariusStore.getState().activeProjectId!==projectId)return;rememberWorkspaceValue(`create:${projectId}:section`,"ideas");useDariusStore.getState().setView("create");onClose();}
  return createPortal(<dialog ref={dialog} className="prompt-transfer idea-save-dialog" aria-labelledby={heading} onKeyDown={e=>e.stopPropagation()} onCancel={e=>{e.preventDefault();if(!busy)onClose();}}><header><div><small>Create / Ideas</small><h2 id={heading}>Save idea</h2></div><button type="button" className="icon-button" aria-label="Close save idea" disabled={busy} onClick={onClose}><X size={18}/></button></header><div className="prompt-transfer-body">{saved ? <><p role="status">Saved “{saved.title}” to Create → Ideas.</p><button type="button" className="primary-button" onClick={openIdeas}><ArrowUpRight size={15}/>Open saved ideas</button></> : <><p>Keep this concept with your project. You can refine the text before saving.</p><label>Title<input aria-label="Idea title" value={title} maxLength={160} disabled={busy} onChange={e=>setTitle(e.target.value)}/></label><label>Idea<textarea aria-label="Idea text" value={content} rows={9} disabled={busy} onChange={e=>setContent(e.target.value)}/></label><small>{content.length.toLocaleString()} / 30,000 characters</small><button type="button" className="primary-button" disabled={busy||!title.trim()||!content.trim()||content.length>30000||sourceText.length>30000} onClick={()=>void save()}><BookmarkPlus size={15}/>{busy?"Saving…":"Save to Create"}</button></>}{error?<p role="alert">{error}</p>:null}</div></dialog>,document.body);
}

export function CreativeIdeas({projectId}:{projectId:string}) {
  const [archived,setArchived]=useState(false),[search,setSearch]=useState(""),[busy,setBusy]=useState<string|null>(null),[error,setError]=useState(""),[copied,setCopied]=useState("");
  const client=useQueryClient();
  const query=useQuery({queryKey:["creative-ideas",projectId,archived],queryFn:()=>ideasApi.list(projectId,archived),refetchInterval:15000});
  useEffect(()=>subscribeProjectRefresh(projectId,event=>{if(event.full||event.types.some(t=>t.startsWith("idea.")))void client.invalidateQueries({queryKey:["creative-ideas",projectId]});}),[client,projectId]);
  async function change(idea:CreativeIdea){if(busy)return;setBusy(idea.id);setError("");try{await ideasApi.state(projectId,idea,!idea.archived);await client.invalidateQueries({queryKey:["creative-ideas",projectId]});}catch(err){setError((err as Error).message);}finally{setBusy(null);}}
  const visible=query.data?.filter(idea=>`${idea.title}\n${idea.content}`.toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  return <section className="creative-ideas" aria-label="Saved project ideas"><header><div><small>From your conversations</small><h2>Ideas worth keeping</h2><p>Concepts and directions saved for this project.</p></div><button type="button" className="secondary-button" onClick={()=>useDariusStore.getState().setView("talk")}>Discuss an idea<ArrowUpRight size={15}/></button></header><div className="ideas-tools"><label>Search ideas<input aria-label="Search ideas" type="search" value={search} onChange={e=>setSearch(e.target.value)}/></label><label><input type="checkbox" checked={archived} onChange={e=>setArchived(e.target.checked)}/>Show archived</label></div>{query.isPending?<p role="status">Loading saved ideas…</p>:query.isError?<p role="alert">Could not load ideas. <button type="button" onClick={()=>void query.refetch()}>Retry</button></p>:!query.data?.length?<div className="ideas-empty"><Lightbulb size={28}/><h3>{archived?"No archived ideas":"Your next idea starts in conversation"}</h3><p>Use Save idea on a chat reply to keep a concept here.</p></div>:!visible?.length?<p>No ideas match your search.</p>:<div className="ideas-grid">{visible.map(idea=><article className="idea-card" key={idea.id}><small>Saved idea</small><h3>{idea.title}</h3><div className="idea-copy">{idea.content}</div><footer><button type="button" className="secondary-button" onClick={()=>void navigator.clipboard.writeText(idea.content).then(()=>setCopied(idea.id)).catch(()=>setError("Select the idea text and use Copy on your device."))}><Copy size={14}/>{copied===idea.id?"Copied":"Copy"}</button><button type="button" className="text-button" disabled={Boolean(busy)} onClick={()=>void change(idea)}>{idea.archived?<RotateCcw size={14}/>:<Archive size={14}/>} {idea.archived?"Restore":"Archive"}</button></footer></article>)}</div>}{error?<p role="alert">{error}</p>:null}</section>;
}
