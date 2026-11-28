# Campaign-neutral response depot v2

This original, optional writing pack extends the preserved depot v1 with
104 authored variants: 56 system responses and 48 editable player drafts.
In total it contains 806 system responses, 298 player drafts, 140 families
and 39 recipes. These are stored variants, not generated combinations.

The new families cover received refusals, acceptances, requests, conditions
and withdrawals; a deferred host status; an unknown civil time; and editable
intentions to introduce oneself, ask permission, offer or seek help, express a
boundary and seek rest. The same language can be used in a station, a court,
a neighborhood or another setting when its stated source and state are present.

Load this file explicitly with `scripted_responses.load_library(path)`. The
default remains the unchanged `depot_v1/library.json`; Engine and App adoption
of v2 is not established here. Formatting uses the existing local, deterministic
composer and does not dispatch a provider call. A trusted host must supply only
information the current actor may receive, with the matching actor, snapshot,
source kind and state. Slot values are inserted as literal text.

Received words must remain the words actually received. An acceptance does not
by itself establish fulfillment, a transfer or permission beyond its terms. An
editable draft is an intention for the player to review and submit, not an
action or another person's consent. For a committed result, the exact
`receipt.exact` anchor remains required and unchanged; presentation cannot
create or change an Engine outcome. The App must escape plain text for its
display surface.

The original depot, compatibility fixtures, archive and campaign records remain
intact. Schema validation is not proof of integration, truth of host facts,
playable campaigns or live-provider quality.
