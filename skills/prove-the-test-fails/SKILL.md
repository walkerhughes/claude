---
name: prove-the-test-fails
description: Break the code under test to confirm a test can actually fail, and fails for the right reason, before trusting it. Use after writing or changing a test, before citing a green run as evidence that something works, when a test has never been seen red, when a suite is said to enforce a contract or invariant, or when an assertion could be satisfied by an empty or degenerate result.
---

# Prove the test fails

A test is not evidence until it has been observed failing for the reason it exists. A green
run says the assertions did not raise; it does not say they could. So break the thing the
test guards, and watch what happens.

Two things follow. Break at the seam the test claims to guard rather than wherever a break
is easy, because a red run the test did not cause proves nothing about that test. And
surviving a mutation does not make a test decorative, since it may assert something the
mutation left true. The question is never whether a test survived but whether it can fail
for the reason it exists, so re-aim at its own claim before calling it decorative.

## The loop

1. **Pick the mutation.** The smallest change to the code under test that should trip this
   test, applied where the test says it is looking. If it claims two implementations agree,
   break one of them. Not a shared import, a fixture, or a build setting: those fail
   everything and say nothing about the test in front of you.
2. **Run the suite and read the output**, not the exit code.
3. **Confirm the failure is the right one.** The test under scrutiny is among the failures,
   and its message names what that test protects. A run that dies in an import or a fixture
   has verified nothing.
4. **Confirm the blast radius.** Where one test body runs over several inputs or
   implementations, breaking one must fail its own cases and leave the rest green. The
   wrong radius means the test measures something other than its name.
5. **Revert and confirm the suite is green.** Always, and before anything else. A mutation
   left behind is a broken repository.

One mutation at a time, so the failures have one cause. Independent seams are therefore
independent runs, and the loop fans out: give each seam its own working copy, run the loop
there, and collect which cases each break turned red.

## An assertion that cannot fail

Assertions about shape rather than content go vacuous quietly. A contract test comparing
the result types of two implementations, on an input that matches nothing, reduces to
comparing two empty sets: it passes, it names a contract, and it guards nothing. Sorted key
lists, lengths, and non-null checks fail the same way. Suspect those first, along with any
green never yet contradicted.

## Evidence, not a count

> Made the cache's read return nothing unconditionally. All 8 cases in the `redis` group
> failed, the 8 `memory` cases passed, nothing else moved. Reverted, suite green.

The mutation, the cases that failed, the cases that did not, and the confirmed revert are
evidence. "50 tests pass" is not.
