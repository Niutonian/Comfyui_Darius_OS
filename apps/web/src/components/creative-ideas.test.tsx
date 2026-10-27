import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { CreativeIdeas, SaveIdeaDialog } from "./creative-ideas";
import { ideasApi, type CreativeIdea } from "@/lib/creative-ideas";

const source="An alien postal worker with an orange uniform.";
const saved:CreativeIdea={id:"idea",projectId:"p",revision:"revision",title:"Alien post",content:source,sourceMessageId:"reply",sourceText:source,conversationId:"chat",archived:false,updatedAt:"2026-10-26"};
function show(node:React.ReactNode){return render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false,gcTime:0}}})}>{node}</QueryClientProvider>);}
beforeEach(()=>{
 Object.defineProperty(HTMLDialogElement.prototype,"showModal",{configurable:true,value:function(this:HTMLDialogElement){this.setAttribute("open","");}});
 Object.defineProperty(HTMLDialogElement.prototype,"close",{configurable:true,value:function(this:HTMLDialogElement){this.removeAttribute("open");}});
 vi.spyOn(ideasApi,"save").mockResolvedValue(saved);
 vi.spyOn(ideasApi,"list").mockResolvedValue([saved]);
 vi.spyOn(ideasApi,"state").mockResolvedValue({...saved,archived:true});
});
afterEach(()=>{cleanup();vi.restoreAllMocks();});
it("reviews text before explicitly saving an idea, retaining its source",async()=>{
 show(<SaveIdeaDialog projectId="p" messageId="reply" sourceText={source} onClose={vi.fn()}/>);
 expect(ideasApi.save).not.toHaveBeenCalled();
 fireEvent.change(screen.getByRole("textbox",{name:"Idea title"}),{target:{value:"Postal world"}});
 fireEvent.change(screen.getByRole("textbox",{name:"Idea text"}),{target:{value:"An explicitly refined concept."}});
 fireEvent.click(screen.getByRole("button",{name:"Save to Create"}));
 await screen.findByRole("status");
 expect(ideasApi.save).toHaveBeenCalledWith("p",expect.objectContaining({title:"Postal world",content:"An explicitly refined concept.",sourceMessageId:"reply",sourceText:source}));
});
it("keeps the reviewed text and save identity after an uncertain response",async()=>{
 vi.mocked(ideasApi.save).mockRejectedValueOnce(new Error("Connection lost"));
 show(<SaveIdeaDialog projectId="p" messageId="reply" sourceText={source} onClose={vi.fn()}/>);
 fireEvent.click(screen.getByRole("button",{name:"Save to Create"}));await screen.findByText("Connection lost");
 expect(screen.getByRole("textbox",{name:"Idea text"})).toHaveValue(source);
 fireEvent.click(screen.getByRole("button",{name:"Save to Create"}));await screen.findByRole("status");
 expect(vi.mocked(ideasApi.save).mock.calls[0][1].id).toBe(vi.mocked(ideasApi.save).mock.calls[1][1].id);
});
it("shows saved ideas, filters them and archives through the versioned state endpoint",async()=>{
 show(<CreativeIdeas projectId="p"/>);await screen.findByText("Alien post");
 fireEvent.change(screen.getByRole("searchbox",{name:"Search ideas"}),{target:{value:"ship"}});expect(screen.getByText("No ideas match your search.")).toBeVisible();
 fireEvent.change(screen.getByRole("searchbox",{name:"Search ideas"}),{target:{value:"orange"}});expect(screen.getByText("Alien post")).toBeVisible();
 fireEvent.click(screen.getByRole("button",{name:"Archive"}));await waitFor(()=>expect(ideasApi.state).toHaveBeenCalledWith("p",saved,true));
});
