import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CreativeMessage } from "./creative-message";
import { mossApi, type MossBoard } from "@/lib/moss-workspace";
import { promptApi, type PromptTarget, type PromptReceipt } from "@/lib/prompt-transfer";
import { canvasApi } from "@/lib/canvas-api";
import { clearWorkspaceSession, rememberWorkspaceValue } from "@/lib/workspace-session";
import type { Message } from "@/lib/types";
import { emptyCanvas } from "@/lib/canvas-document";

const board = { id:"board", projectId:"p", documentId:"doc", name:"Alien", kind:"moss-t2i", revision:1, documentRevision:1, archived:false, settings:{adapterVersion:"moss-bboxes-v1",seed:42,references:[]} , artboard:{width:1024,height:1024,preset:"square"},prompt:"",regionCount:0,layout:[],activeResult:null,previewAssetId:null,latest:null,jobs:[],newResult:false } satisfies MossBoard;
const target: PromptTarget = { boardId:"board",documentId:"doc",name:"Alien",archived:false,boardRevision:1,documentRevision:1,destination:{key:"layout:moss-bboxes-v1",label:"MOSS / Global scene prompt",family:"MOSS",mode:"moss-bboxes-v1",maxLength:6000},text:"An older scene" };
const text = "An alien in an orange uniform.\n\nRain on its visor.";
const message: Message = { id:"reply",conversation_id:"chat",role:"assistant",content:`Here are two directions.\n\n\`\`\`prompt Alien mail\n${text}\n\`\`\`\n\nAn explanation.\n\n\`\`\`prompt Forest\nA silent green forest.\n\`\`\``,created_at:"",metadata:{prompt_drafts:[{id:"draft-a",title:"Alien mail",text},{id:"draft-b",title:"Forest",text:"A silent green forest."}]} };
const receipt: PromptReceipt = { transferId:"transfer",undone:false,target:{...target,text},board:{...board,revision:2},document:{id:"doc",projectId:"p",revision:2,content:{...emptyCanvas(),globalPrompt:text},activeGenerationId:null,updatedAt:"",generations:[]} };
function show(m=message) { return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false,gcTime:0}}})}><CreativeMessage message={m} projectId="p" /></QueryClientProvider>); }
beforeEach(()=>{
 clearWorkspaceSession();
 Object.defineProperty(HTMLDialogElement.prototype,"showModal",{configurable:true,value:function(this:HTMLDialogElement){this.setAttribute("open","");}});
 Object.defineProperty(HTMLDialogElement.prototype,"close",{configurable:true,value:function(this:HTMLDialogElement){this.removeAttribute("open");}});
 vi.spyOn(mossApi,"get").mockResolvedValue({projectId:"p",schemaVersion:1,revision:1,placements:[],boards:[board],capacity:1,queuePolicy:""});
 vi.spyOn(promptApi,"review").mockResolvedValue(target);
 vi.spyOn(promptApi,"apply").mockResolvedValue(receipt);
 vi.spyOn(promptApi,"undo").mockResolvedValue({...receipt,undone:true});
 vi.stubGlobal("navigator",{clipboard:{writeText:vi.fn().mockResolvedValue(undefined)}});
});
afterEach(()=>{cleanup();vi.restoreAllMocks();vi.unstubAllGlobals();clearWorkspaceSession();});

it("copies and transfers only the chosen complete draft, with an explicit destination and prompt-only request",async()=>{
 const generate=vi.spyOn(canvasApi,"generate");show();
 fireEvent.click(screen.getAllByRole("button",{name:"Copy"})[0]);
 expect(navigator.clipboard.writeText).toHaveBeenCalledWith(text);
 fireEvent.click(screen.getAllByRole("button",{name:"Use in board"})[0]);
 fireEvent.change(await screen.findByRole("combobox",{name:"Destination board"}),{target:{value:"board"}});
 await screen.findByText("Alien / MOSS / Global scene prompt");
 expect(screen.getByRole("textbox",{name:"Prompt to apply"})).toHaveValue(text);
 expect(screen.getByText("Existing prompt · will be replaced")).toBeVisible();
 fireEvent.click(screen.getByRole("button",{name:"Replace prompt"}));
 await screen.findByText("Prompt added to Alien");
 expect(promptApi.apply).toHaveBeenCalledWith("p","board",expect.objectContaining({sourceMessageId:"reply",sourceDraftId:"draft-a",sourceText:text,text,boardRevision:1,documentRevision:1,destination:target.destination.key}));
 expect(generate).not.toHaveBeenCalled();
 fireEvent.click(screen.getByRole("button",{name:"Undo"}));await screen.findByText("Prompt transfer undone");
 expect(promptApi.undo).toHaveBeenCalledWith("p","board","transfer");
});

it("retains the text after a cross-device conflict and requires a refreshed target review",async()=>{
 vi.mocked(promptApi.apply).mockRejectedValueOnce(new Error("The board changed on another device"));show();
 fireEvent.click(screen.getAllByRole("button",{name:"Use in board"})[0]);
 fireEvent.change(await screen.findByRole("combobox",{name:"Destination board"}),{target:{value:"board"}});
 await screen.findByText("Alien / MOSS / Global scene prompt");
 fireEvent.change(screen.getByRole("textbox",{name:"Prompt to apply"}),{target:{value:"My reviewed correction"}});
 fireEvent.click(screen.getByRole("button",{name:"Replace prompt"}));await screen.findByText("The board changed on another device");
 expect(screen.getByRole("textbox",{name:"Prompt to apply"})).toHaveValue("My reviewed correction");
 vi.mocked(promptApi.review).mockResolvedValueOnce({...target,boardRevision:2,documentRevision:3});
 fireEvent.click(screen.getByRole("button",{name:"Refresh target review"}));await waitFor(()=>expect(promptApi.review).toHaveBeenCalledTimes(2));
 await screen.findByText("Alien / MOSS / Global scene prompt");fireEvent.click(screen.getByRole("button",{name:"Replace prompt"}));
 await screen.findByText("Prompt added to Alien");expect(vi.mocked(promptApi.apply).mock.calls[1][2]).toMatchObject({text:"My reviewed correction",boardRevision:2,documentRevision:3});
});

it("offers plain-text selection fallback without converting ordinary discussion into a card",async()=>{
 const m={...message,content:"A discussion about orange uniforms.",metadata:{}};show(m);
 expect(screen.queryByRole("button",{name:"Use in board"})).toBeNull();
 fireEvent.click(screen.getByRole("button",{name:"Use selected text or reply in board"}));
 expect(screen.getByRole("textbox",{name:"Prompt to apply"})).toHaveValue(m.content);
});

it("shows an empty state and keeps the prompt editable without implicitly adding a board",async()=>{
 vi.mocked(mossApi.get).mockResolvedValue({projectId:"p",schemaVersion:1,revision:1,placements:[],boards:[],capacity:1,queuePolicy:""});const add=vi.spyOn(mossApi,"add");show();
 fireEvent.click(screen.getAllByRole("button",{name:"Use in board"})[0]);await screen.findByText(/No available boards/);
 expect(screen.getByRole("textbox",{name:"Prompt to apply"})).toHaveValue(text);expect(add).not.toHaveBeenCalled();expect(screen.getByRole("button",{name:"Apply prompt"})).toBeDisabled();
});

it("refuses to overwrite unsaved local canvas edits",async()=>{
 const clean=emptyCanvas();rememberWorkspaceValue("canvas:p:doc:draft",{revision:1,saved:clean,history:{past:[],present:{...clean,globalPrompt:"Unsaved local thought"},future:[]}});show();
 fireEvent.click(screen.getAllByRole("button",{name:"Use in board"})[0]);fireEvent.change(await screen.findByRole("combobox",{name:"Destination board"}),{target:{value:"board"}});
 await screen.findByText("Alien / MOSS / Global scene prompt");fireEvent.click(screen.getByRole("button",{name:"Replace prompt"}));await screen.findByText(/unsaved canvas edits/);expect(promptApi.apply).not.toHaveBeenCalled();
});

it("reuses a transfer identity after an uncertain network result",async()=>{
 vi.mocked(promptApi.apply).mockRejectedValueOnce(new Error("Connection interrupted"));show();fireEvent.click(screen.getAllByRole("button",{name:"Use in board"})[0]);fireEvent.change(await screen.findByRole("combobox",{name:"Destination board"}),{target:{value:"board"}});
 await screen.findByText("Alien / MOSS / Global scene prompt");fireEvent.click(screen.getByRole("button",{name:"Replace prompt"}));await screen.findByText("Connection interrupted");fireEvent.click(screen.getByRole("button",{name:"Replace prompt"}));await screen.findByText("Prompt added to Alien");
 expect(vi.mocked(promptApi.apply).mock.calls[0][2].transferId).toBe(vi.mocked(promptApi.apply).mock.calls[1][2].transferId);
});
