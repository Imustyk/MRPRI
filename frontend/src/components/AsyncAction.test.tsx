import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { AsyncButton, AsyncForm } from "./AsyncAction";
import { ConfirmButton } from "../ui";
import { StatusEditor } from "../pages/Workspace";
import "../i18n";
describe("awaited actions", () => {
 it("locks double submit and retains draft after failure", async () => {
  let reject!: (reason: Error) => void; const save = vi.fn(() => new Promise<void>((_,r) => { reject=r; }));
  render(<AsyncForm onSubmit={save}><input aria-label="draft" defaultValue="retain"/><button>Save</button></AsyncForm>);
  const form = screen.getByRole("button",{name:"Save"}).closest("form")!;
  fireEvent.submit(form);fireEvent.submit(form);expect(save).toHaveBeenCalledTimes(1);
  reject(new Error("offline"));await screen.findByRole("alert");expect((screen.getByLabelText("draft") as HTMLInputElement).value).toBe("retain");expect(screen.getByRole("button",{name:"Save"}).hasAttribute("disabled")).toBe(false);
 });
 it("button awaits refusal then can retry", async () => {const save=vi.fn().mockRejectedValueOnce(new Error("refused")).mockResolvedValueOnce(undefined); render(<AsyncButton onClick={save}>Update</AsyncButton>);fireEvent.click(screen.getByRole("button"));await screen.findByRole("alert");fireEvent.click(screen.getByRole("button"));await waitFor(()=>expect(save).toHaveBeenCalledTimes(2));});
 it("confirmation failure stays armed and does not repeat during pending",async () => {let reject!:(e:Error)=>void;const remove=vi.fn(()=>new Promise<void>((_,r)=>{reject=r;}));render(<ConfirmButton onConfirm={remove} confirmLabel="Really delete?">Delete</ConfirmButton>);fireEvent.click(screen.getByRole("button",{name:"Delete"}));const confirm=screen.getByRole("button",{name:"Really delete?"});fireEvent.click(confirm);fireEvent.click(confirm);expect(remove).toHaveBeenCalledTimes(1);reject(new Error("denied"));await screen.findByRole("alert");expect(screen.getByRole("button",{name:"Really delete?"})).toBeTruthy();});
 it("status rolls back on refusal and synchronizes refreshed props",async()=>{const update=vi.fn().mockRejectedValue(new Error("denied"));const {rerender}=render(<StatusEditor value="open" options={["open","closed"]} onChange={update}/>);fireEvent.change(screen.getByRole("combobox"),{target:{value:"closed"}});await screen.findByRole("alert");expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("open");rerender(<StatusEditor value="closed" options={["open","closed"]} onChange={update}/>);expect((screen.getByRole("combobox") as HTMLSelectElement).value).toBe("closed");});
});
