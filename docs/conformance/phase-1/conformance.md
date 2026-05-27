# Conformance Report

- contracts_sha: `0x1827cdd5211f606e9c50af170d38a6135a251592b5ed775b66e3cd3b7ba501ce`
- run_id: `20260527T051924Z-ab1e77d`
- fixture_count: 145
- call_count: 1976

## Totals

| PASS | FAIL | GAP | ERROR | Has error |
| ---: | ---: | ---: | ---: | :--- |
| 663 | 24 | 1289 | 0 | False |

## Per-power Gate

| Power | PASS | FAIL | GAP | ERROR | Gate |
| :--- | ---: | ---: | ---: | ---: | :--- |
| legislative | 663 | 24 | 1289 | 0 | FAIL |

## Top FAILures

- legislation/ConstitutionalReview/testRevert_reviewProposal_alreadyReviewed_reverts call 0 ConstitutionalReview.reviewProposal(bytes32,bool,bytes32)
- legislation/ConstitutionalReview/testRevert_reviewProposal_alreadyReviewed_reverts call 1 ConstitutionalReview.reviewProposal(bytes32,bool,bytes32)
- legislation/ConstitutionalReview/testRevert_reviewProposal_whenPaused_reverts call 0 ConstitutionalReview.pause()
- legislation/ConstitutionalReview/testRevert_reviewProposal_whenPaused_reverts call 1 ConstitutionalReview.reviewProposal(bytes32,bool,bytes32)
- legislation/ConstitutionalReview/testRevert_reviewProposal_withoutRole_reverts call 0 ConstitutionalReview.reviewProposal(bytes32,bool,bytes32)
- legislation/ConstitutionalReview/testRevert_reviewProposal_zeroProposalId_reverts call 0 ConstitutionalReview.reviewProposal(bytes32,bool,bytes32)
- legislation/ConstitutionalReview/testRevert_setConstitutionalParams_withoutRole_reverts call 0 ConstitutionalReview.setConstitutionalParams(address)
- legislation/ConstitutionalReview/testRevert_setConstitutionalParams_zeroAddress_reverts call 0 ConstitutionalReview.setConstitutionalParams(address)
- legislation/ConstitutionalReview/test_hasPassed_falseAfterFailedVerdict call 0 ConstitutionalReview.reviewProposal(bytes32,bool,bytes32)
- legislation/ConstitutionalReview/test_hasPassed_falseAfterFailedVerdict call 1 ConstitutionalReview.hasPassed(bytes32)

## Top GAPs

- legislation/CodificationModule/testRevert_addToWhitelist_duplicate call 0 CodificationModule.addToWhitelist(bytes32)
- legislation/CodificationModule/testRevert_addToWhitelist_noRole call 0 CodificationModule.WHITELIST_ROLE()
- legislation/CodificationModule/testRevert_addToWhitelist_noRole call 1 CodificationModule.addToWhitelist(bytes32)
- legislation/CodificationModule/testRevert_addToWhitelist_zeroHash call 0 CodificationModule.addToWhitelist(bytes32)
- legislation/CodificationModule/testRevert_codify_noRole call 0 CodificationModule.CODIFIER_ROLE()
- legislation/CodificationModule/testRevert_getRecord_notFound call 0 CodificationModule.getRecord(bytes32)
- legislation/CodificationModule/testRevert_recordDeployment_noRole call 1 CodificationModule.DEPLOYER_ROLE()
- legislation/CodificationModule/testRevert_removeFromWhitelist_noRole call 0 CodificationModule.WHITELIST_ROLE()
- legislation/CodificationModule/testRevert_removeFromWhitelist_noRole call 1 CodificationModule.removeFromWhitelist(bytes32)
- legislation/CodificationModule/testRevert_removeFromWhitelist_notWhitelisted call 0 CodificationModule.removeFromWhitelist(bytes32)
