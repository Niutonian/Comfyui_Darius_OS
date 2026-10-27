# Workflow loading and shot plans

Darius parses the message content of Responses API output, including when a
reasoning item comes first. A malformed/incomplete visual-brief response gets one
bounded text-only repair attempt. A refusal remains a refusal. No rendering is
part of brief extraction.

Visual plans are scoped to the original project/message. They distinguish one
brief with repeated takes from 2–6 separate shot briefs. Each shot keeps its own
prompt, character IDs, canonical appearances, and chosen project reference IDs.
The resolver receives approved character references and bounded evidence from
asset searches/details/inspection. Asset ownership is checked again at binding.

For separate shots, tools prepare one immutable workflow per `brief_id` (`shot-1`,
etc.). Workflows may differ between shots. Render slots are keyed by message and
shot index: a retry returns the existing job for that slot, including when shots
were queued out of order. It never substitutes the last prepared graph for a
missing shot. A premature final response returns to planning until remaining
shots are handled or the bounded turn budget is reached. Explicit retry refreshes
the model/tool configuration and per-attempt budget while retaining completed
steps and render associations. A changed plan needs a new message once jobs exist.

Inspection reports connected positive/negative text and image inputs. Distinct
positive slots require `prompt_bindings` for all slots, with values `shot` or
`subject:<character_id>`. This supports separate regional subjects and dual text
encoders without changing negative conditioning. Literal dotted node IDs and input
names resolve against the graph itself. Unknown layouts require inspection and
mapping; Darius does not invent their semantics. Identical positive strings can
share one brief. Review preserves compiled assistant-workflow inputs.

Malformed definitions and duplicate IDs are excluded individually and reported
in service health. File changes refresh the registry for API and workers. A
workflow conversion is reused within the current bridge only for identical source
bytes; draft validation still runs. Old conversion/render evidence does not rank
a changed source, and a failed conversion cannot outrank usable candidates merely
because it is a managed default.

Failures record a category, recovery action and whether they are transient.
Completed chat messages show error details in tool activity. Identical failed tool
calls are suppressed within an attempt. Retrying does not recreate existing render
slots or automatically resend a paid BFL generation. Chat displays individual shot
review entries with their own prompts/references and links saved jobs.

Limits: this does not guarantee every external model/node will succeed. Missing
models, unavailable services, unknown graph semantics and ambiguous identities
remain actionable blockers. Local standing permission still requires verified
local nodes. Paid/cloud operations retain explicit approval. A later video stage
does not silently run while the current request is generating its image frames.

Verification includes a live GPT-6 Luna text-only check producing three distinct
fictional scenes with Ellie/Ellie/Ellie-and-Giorgio subject membership; mocked render
tests cover independent shot prompts, out-of-order queueing, duplicate prevention,
partial-plan continuation, regional prompt mapping, registry repair and project
reference validation. No real image/video generation was submitted by these checks.
