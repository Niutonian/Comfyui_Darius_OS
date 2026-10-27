"use client";

import { useState } from "react";

export function WorkflowJsonInput({ value, disabled, onChange, onInvalid }: { value: unknown; disabled: boolean; onChange: (value: unknown) => void; onInvalid: (invalid: boolean) => void }) {
  const [text, setText] = useState(() => value === undefined ? "" : JSON.stringify(value, null, 2));
  const [invalid, setInvalid] = useState(false);
  return <><textarea rows={4} disabled={disabled} value={text} aria-invalid={invalid} placeholder={'["asset:project-image-id"] or [[0, "asset:first-frame-id"], [8, "asset:last-frame-id"]]'} onChange={(event) => {
    const next = event.target.value;
    setText(next);
    try {
      onChange(next.trim() ? JSON.parse(next) : undefined);
      setInvalid(false);
      onInvalid(false);
    } catch {
      setInvalid(true);
      onInvalid(true);
    }
  }} /><small>JSON value. Use &quot;asset:ID&quot; for project media, or an explicit API URL. Timed keyframes use [seconds, image] pairs.</small>{invalid ? <small className="form-error" role="alert">Enter valid JSON before reviewing this generation.</small> : null}</>;
}
