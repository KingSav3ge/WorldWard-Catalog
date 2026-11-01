# Catalog finite convergence checkpoint

The sole existing Catalog owner consolidates two present review histories from published Catalog a18cb48928da25d40d057a182c69f71ef149ce80:

- ce4e503e7464e899092cb65917a1b005fa8a01c4: additive fictional expansion proposals v1/v2 and their structural tests. These remain PROPOSED, UNSELECTED and unimplemented. Including source documents does not activate an Engine allowance, council, permission or campaign.
- e94a91a941b43f33ea02881af87261b13211d42f: the sustained consumer's timing correction, with failed 932bf5007386c8d5fe67cf6f7bb1ab3356025153 preserved as its parent.

This merge additionally admits explicitly supplied compatible test commits. It does not add gameplay, catalogue content, selectable profiles or numeric policy. The existing proposal and consumer branch tips are preserved. Inaccessible owner-local work has not been inspected, overwritten or adopted; recovery requires later CMRR of any unique changes.

The consumer's historical invocation remains reproducible with Engine ecca8094a2d2cdb8a11e018a085487288b26e88d and App c04ba5524ae95316c7e826fc63085a4916d7dd67. That App actually pins the same Engine and Catalog a18cb48928da25d40d057a182c69f71ef149ce80, so a newer Catalog test is honestly labeled an override. Compatible mode requires full immutable Engine/App/Catalog SHAs, clean exact checkouts and matching actual App gitlinks; it rejects a mismatched set. Actual test identity is recorded separately from fixture provenance. No future App SHA or self-Catalog SHA is embedded in fixture hashes.

## Required exact-candidate checks

Use isolated clean sources and synthetic temporary stores. Resolve catalog_convergence_sha to the reviewed containing commit, never a moving main ref. Output stays outside source checkouts.

    python -B -m unittest tools.tests.test_proposed_rise_expansion_contract tools.tests.test_proposed_rise_expansion_v2_contract -v
    python -B IRGS_Catalog/verify_catalog.py
    python -B tools/tests/test_sustained_ordinary_consumers.py --engine-source "$baseline_engine_checkout" --app-source "$baseline_app_checkout" --catalog-commit "$catalog_convergence_sha" --output /tmp/catalog-convergence-baseline.json --require-g10

The first two commands require passing structural/integrity results. The strict consumer requires two bounded runtime passes, no skips, and held exit 2. Runtime failure or source-admission rejection returns 1 and cannot be relabeled held success. Compatible mode with the historical App and this newer Catalog must intentionally reject the mismatched Catalog pin; record that negative admission check separately.

After the App owner commits the actual Engine/Catalog selections, the coordinator must test the actual final compatible set:

    python -B tools/tests/test_sustained_ordinary_consumers.py --selection-mode compatible --engine-source "$engine_checkout" --engine-commit "$selected_engine_sha" --app-source "$app_checkout" --app-commit "$selected_app_sha" --catalog-commit "$catalog_convergence_sha" --output /tmp/catalog-convergence-compatible.json --require-g10

No execution of this changed consolidation is claimed by this authoring checkpoint. Earlier coordinator evidence belongs to its original SHA, including the failed 932bf500 run. Actual commands, results and any skips for this candidate belong in the coordinator receipt.

## Publication and stop

Feature and proposal development stops at this finite consolidation. After coordinator test acceptance, the Catalog owner may fast-forward Catalog main ordinarily to this reviewed merge. Recheck remote main first; never force or bypass protection. Read back the main SHA and CI status. The coordinator alone assembles, versions and publishes the joined increment; current published source is 3.4.8 Pre-Alpha, not qualified Alpha 5.0.

The original ALPHA_4_0_PLAN.md gate and all seven acceptance journeys at joined 3f174ffad14e2219c483dd5366bb56254e08a401 remain. Concrete sustained recovery, continuing agency and risk/recovery gaps are open. Unselected proposal numbers or the fictional council are not automatically release-minimum policy. No live-provider, Windows or full G10/Alpha qualification is asserted.
