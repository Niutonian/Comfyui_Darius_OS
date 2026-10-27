"use client";

import { useMutation } from "@tanstack/react-query";
import { Check, ChevronDown, FolderPlus, LoaderCircle, Pencil, Trash2, X } from "lucide-react";
import { FormEvent, useCallback, useState } from "react";
import { api, ApiError } from "@/lib/api-client";
import { useDariusStore } from "@/lib/store";
import { useMobileSheetFocus } from "@/lib/use-mobile-shell";

export function ProjectSelector({ homeSignal = 0, compact = false }: { homeSignal?: number; compact?: boolean }) {
  const { projects, activeProjectId, setActiveProject, addProject, setProjects } = useDariusStore();
  const [open, setOpen] = useState(false);
  const close = useCallback(() => setOpen(false), []);
  useMobileSheetFocus(compact && open ? ".project-menu" : null, close);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingName, setEditingName] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);
  const active = projects.find((project) => project.id === activeProjectId);
  const [seenHomeSignal, setSeenHomeSignal] = useState(homeSignal);
  if (homeSignal !== seenHomeSignal) {
    setSeenHomeSignal(homeSignal);
    if (homeSignal > 0) {
      setCreating(false);
      setOpen(true);
    }
  }
  const mutation = useMutation({
    mutationFn: api.createProject,
    onSuccess: (project) => {
      addProject(project);
      setName("");
      setDescription("");
      setCreating(false);
      setOpen(false);
    },
  });

  function submit(event: FormEvent) {
    event.preventDefault();
    if (name.trim()) mutation.mutate({ name: name.trim(), description: description.trim() });
  }

  async function removeProject(projectId: string, projectName: string) {
    if (!window.confirm(`Delete project “${projectName}” and all of its media? This cannot be undone.`)) return;
    await api.deleteProject(projectId);
    const remaining = projects.filter((project) => project.id !== projectId);
    setProjects(remaining);
    if (projectId === activeProjectId) setActiveProject(remaining[0]?.id ?? null);
  }

  async function saveProjectName(projectId: string) {
    const nextName = editingName.trim();
    if (!nextName) return;
    setSavingId(projectId);
    try {
      const updated = await api.updateProject(projectId, { name: nextName });
      setProjects(projects.map((project) => project.id === updated.id ? updated : project));
      setEditingId(null);
    } finally {
      setSavingId(null);
    }
  }

  return (
    <div className="project-select">
      <button
        aria-expanded={open}
        className="project-trigger"
        onClick={() => setOpen((value) => !value)}
        type="button"
      >
        <span className="project-mark">D</span>
        <span><small>Current project</small><strong>{active?.name ?? "Choose a project"}</strong></span>
        <ChevronDown size={16} aria-hidden="true" />
      </button>
      {open ? (
        <><button className="mobile-project-scrim" aria-label="Dismiss projects" onClick={close} type="button" />
        <div className="project-menu" role={compact ? "dialog" : undefined} aria-modal={compact ? true : undefined} aria-label="Choose project">
          <div className="menu-heading">
            <span>Your projects</span>
            <button aria-label="Close projects" className="icon-button" onClick={() => setOpen(false)} type="button"><X size={16} /></button>
          </div>
          <div className="project-list" aria-label="Projects">
            {projects.length ? projects.map((project) => editingId === project.id ? (
              <form className="project-option project-option-edit" key={project.id} onSubmit={(event) => { event.preventDefault(); void saveProjectName(project.id); }}>
                <input aria-label={`Edit project name ${project.name}`} autoFocus maxLength={200} onChange={(event) => setEditingName(event.target.value)} value={editingName} />
                <span className="project-option-actions"><button aria-label="Save project name" className="icon-button" disabled={savingId === project.id || !editingName.trim()} type="submit"><Check size={15} /></button><button aria-label="Cancel project name edit" className="icon-button" onClick={() => setEditingId(null)} type="button"><X size={15} /></button></span>
              </form>
            ) : (
              <button className="project-option" key={project.id} onClick={() => { setActiveProject(project.id); setOpen(false); }} type="button">
                <span><strong>{project.name}</strong><small>{project.description || "No description"}</small></span>
                <span className="project-option-actions">{project.id === activeProjectId ? <Check size={16} aria-label="Selected" /> : null}<span aria-label={`Edit project ${project.name}`} className="icon-button" role="button" onClick={(event) => { event.stopPropagation(); setEditingId(project.id); setEditingName(project.name); }} title="Edit project name"><Pencil size={14} /></span><span aria-label={`Delete project ${project.name}`} className="icon-button" role="button" onClick={(event) => { event.stopPropagation(); void removeProject(project.id, project.name); }} title="Delete project"><Trash2 size={14} /></span></span>
              </button>
            )) : <p className="menu-empty">Create your first server-backed project to begin.</p>}
          </div>
          {creating ? (
            <form className="project-form" onSubmit={submit}>
              <label>Project name<input autoFocus maxLength={200} onChange={(event) => setName(event.target.value)} required value={name} /></label>
              <label>Description<textarea maxLength={5000} onChange={(event) => setDescription(event.target.value)} rows={2} value={description} /></label>
              {mutation.error ? <p className="form-error" role="alert">{mutation.error instanceof ApiError ? mutation.error.message : "Project creation failed."}</p> : null}
              <div className="form-actions">
                <button className="text-button" onClick={() => setCreating(false)} type="button">Cancel</button>
                <button className="primary-button compact" disabled={mutation.isPending || !name.trim()} type="submit">
                  {mutation.isPending ? <LoaderCircle className="spin" size={15} /> : null} Create
                </button>
              </div>
            </form>
          ) : (
            <button className="new-project" onClick={() => setCreating(true)} type="button"><FolderPlus size={17} /> New project</button>
          )}
        </div></>
      ) : null}
    </div>
  );
}
