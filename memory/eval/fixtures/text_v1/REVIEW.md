# Text v1 Gold Corpus Review

All 64 fixtures were reviewed by `dimaa` on 2026-07-10. Offsets, epistemic tags, forbidden rules, and ingestion expectations were validated; smoke ingestion was green before sign-off.

| Fixture | Language | Tier | Slices | Review |
|---|---|---|---|---|
| `ru_relation_001` | ru | smoke | direct_attribute_relation | reviewed |
| `ru_relation_002` | ru | full | direct_attribute_relation, temporal_precision | reviewed |
| `ru_attribute_003` | ru | full | direct_attribute_relation | reviewed |
| `ru_preference_004` | ru | smoke | preference_constraint | reviewed |
| `ru_preference_005` | ru | full | preference_constraint, negation | reviewed |
| `ru_constraint_006` | ru | full | preference_constraint | reviewed |
| `ru_constraint_007` | ru | full | preference_constraint, negation | reviewed |
| `ru_goal_008` | ru | smoke | goal_task_deadline, temporal_precision | reviewed |
| `ru_task_009` | ru | full | goal_task_deadline, temporal_precision | reviewed |
| `ru_task_010` | ru | full | goal_task_deadline, temporal_precision | reviewed |
| `ru_negation_011` | ru | smoke | negation, direct_attribute_relation, hard_negative | reviewed |
| `ru_negation_012` | ru | full | negation, direct_attribute_relation | reviewed |
| `ru_negation_013` | ru | full | negation, preference_constraint | reviewed |
| `ru_negation_014` | ru | full | negation, goal_task_deadline, temporal_precision | reviewed |
| `ru_uncertain_015` | ru | smoke | uncertainty_alternative, direct_attribute_relation, hard_negative | reviewed |
| `ru_uncertain_016` | ru | full | uncertainty_alternative, temporal_precision, multi_turn | reviewed |
| `ru_alternative_017` | ru | full | uncertainty_alternative, preference_constraint, multi_turn | reviewed |
| `ru_correction_018` | ru | full | correction_followup, direct_attribute_relation, multi_turn | reviewed |
| `ru_correction_019` | ru | smoke | correction_followup, direct_attribute_relation, multi_turn | reviewed |
| `ru_followup_020` | ru | full | correction_followup, direct_attribute_relation, multi_turn | reviewed |
| `ru_followup_021` | ru | smoke | correction_followup, preference_constraint, multi_turn, hard_negative | reviewed |
| `ru_quote_022` | ru | full | wrong_speaker_hearsay, preference_constraint, hard_negative, multi_turn | reviewed |
| `ru_hearsay_023` | ru | smoke | wrong_speaker_hearsay, uncertainty_alternative, hard_negative, multi_turn | reviewed |
| `ru_inferred_024` | ru | full | uncertainty_alternative, wrong_speaker_hearsay | reviewed |
| `ru_assistant_025` | ru | full | wrong_speaker_hearsay, irrelevant_abstention, hard_negative | reviewed |
| `ru_question_026` | ru | smoke | irrelevant_abstention, hard_negative | reviewed |
| `ru_sarcasm_027` | ru | full | irrelevant_abstention, hard_negative, preference_constraint | reviewed |
| `ru_image_028` | ru | full | irrelevant_abstention | reviewed |
| `ru_tool_029` | ru | smoke | exact_tool_result, goal_task_deadline, temporal_precision, multi_turn | reviewed |
| `ru_tool_030` | ru | smoke | exact_tool_result, goal_task_deadline, wrong_speaker_hearsay, multi_turn | reviewed |
| `ru_state_031` | ru | smoke | temporal_precision, direct_attribute_relation | reviewed |
| `ru_temporal_032` | ru | full | temporal_precision, direct_attribute_relation, exact_tool_result | reviewed |
| `en_attribute_033` | en | full | direct_attribute_relation | reviewed |
| `en_relation_034` | en | full | direct_attribute_relation | reviewed |
| `en_relation_035` | en | full | direct_attribute_relation | reviewed |
| `en_preference_036` | en | full | preference_constraint | reviewed |
| `en_preference_037` | en | full | preference_constraint, negation | reviewed |
| `en_constraint_038` | en | full | preference_constraint | reviewed |
| `en_constraint_039` | en | full | preference_constraint | reviewed |
| `en_goal_040` | en | full | goal_task_deadline, temporal_precision | reviewed |
| `en_task_041` | en | full | goal_task_deadline | reviewed |
| `en_task_042` | en | full | goal_task_deadline, temporal_precision | reviewed |
| `en_negation_043` | en | smoke | negation, direct_attribute_relation, hard_negative | reviewed |
| `en_negation_044` | en | full | negation, direct_attribute_relation | reviewed |
| `en_negation_045` | en | full | negation, direct_attribute_relation, hard_negative | reviewed |
| `en_negation_046` | en | full | negation, goal_task_deadline, temporal_precision | reviewed |
| `en_uncertain_047` | en | smoke | uncertainty_alternative, temporal_precision, hard_negative, multi_turn | reviewed |
| `en_uncertain_048` | en | full | uncertainty_alternative, preference_constraint | reviewed |
| `en_alternative_049` | en | full | uncertainty_alternative, preference_constraint | reviewed |
| `en_correction_050` | en | full | correction_followup, direct_attribute_relation, multi_turn | reviewed |
| `en_correction_051` | en | full | correction_followup, preference_constraint, multi_turn | reviewed |
| `en_followup_052` | en | full | correction_followup, direct_attribute_relation, multi_turn | reviewed |
| `en_quote_053` | en | full | wrong_speaker_hearsay, preference_constraint, hard_negative | reviewed |
| `en_hearsay_054` | en | full | wrong_speaker_hearsay, uncertainty_alternative, hard_negative | reviewed |
| `en_assistant_055` | en | full | wrong_speaker_hearsay, irrelevant_abstention, hard_negative | reviewed |
| `en_question_056` | en | full | irrelevant_abstention, hard_negative | reviewed |
| `en_sarcasm_057` | en | full | irrelevant_abstention, hard_negative, preference_constraint | reviewed |
| `en_irrelevant_058` | en | full | irrelevant_abstention | reviewed |
| `en_tool_059` | en | smoke | exact_tool_result, goal_task_deadline, multi_turn | reviewed |
| `en_tool_060` | en | full | exact_tool_result, wrong_speaker_hearsay, hard_negative | reviewed |
| `mixed_relation_061` | mixed | full | direct_attribute_relation | reviewed |
| `mixed_preference_062` | mixed | full | preference_constraint | reviewed |
| `mixed_correction_063` | mixed | smoke | correction_followup, direct_attribute_relation, multi_turn, hard_negative | reviewed |
| `mixed_tool_064` | mixed | full | exact_tool_result, goal_task_deadline, temporal_precision | reviewed |
