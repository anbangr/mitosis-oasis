# Conformance Report

- contracts_sha: `0x19e8e5db7d2dce557ecf00eeff05c55c9c230293040f11c2f15719d0dbf9ec54`
- run_id: `20260527T043410Z-1639526`
- fixture_count: 71
- call_count: 1357

## Totals

| PASS | FAIL | GAP | ERROR | Has error |
| ---: | ---: | ---: | ---: | :--- |
| 491 | 24 | 842 | 0 | False |

## Per-power Gate

| Power | PASS | FAIL | GAP | ERROR | Gate |
| :--- | ---: | ---: | ---: | ---: | :--- |
| legislative | 491 | 24 | 842 | 0 | FAIL |

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

- legislation/LegislativePipeline/testFuzz_quorumMath_matchesBpsFormula(uint256,uint256) call 6 AgentRegistry.isActiveAgent(uint256)
- legislation/LegislativePipeline/testFuzz_quorumMath_matchesBpsFormula(uint256,uint256) call 7 AgentRegistry.isAuthorizedOrOwner(address,uint256)
- legislation/LegislativePipeline/testFuzz_quorumMath_matchesBpsFormula(uint256,uint256) call 8 AgentRegistry.isActiveAgent(uint256)
- legislation/LegislativePipeline/testFuzz_quorumMath_matchesBpsFormula(uint256,uint256) call 9 AgentRegistry.isAuthorizedOrOwner(address,uint256)
- legislation/LegislativePipeline/testFuzz_quorumMath_matchesBpsFormula(uint256,uint256) call 10 0x0000000000000000000000000000000000000001.0x0c50fe20
- legislation/LegislativePipeline/testFuzz_quorumMath_matchesBpsFormula(uint256,uint256) call 11 AgentRegistry.isActiveAgent(uint256)
- legislation/LegislativePipeline/testFuzz_quorumMath_matchesBpsFormula(uint256,uint256) call 12 AgentRegistry.isAuthorizedOrOwner(address,uint256)
- legislation/LegislativePipeline/testFuzz_quorumMath_matchesBpsFormula(uint256,uint256) call 13 0x0000000000000000000000000000000000000001.0x66285407
- legislation/LegislativePipeline/testFuzz_quorumMath_matchesBpsFormula(uint256,uint256) call 14 AgentRegistry.isActiveAgent(uint256)
- legislation/LegislativePipeline/testFuzz_quorumMath_matchesBpsFormula(uint256,uint256) call 15 AgentRegistry.isAuthorizedOrOwner(address,uint256)

