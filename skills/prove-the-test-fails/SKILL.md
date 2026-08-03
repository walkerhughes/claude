---
name: prove-the-test-fails
description: Break the code under test to confirm a test can actually fail, and fails for the right reason, before trusting it. Use after writing or changing a test, before citing a green run as evidence that something works, when a test has never been seen red, when a suite is said to enforce a contract or invariant, or when an assertion could be satisfied by an empty or degenerate result.
---

# Prove the test fails

A test you just wrote is not verified until you have watched it fail for the right reason.
A green run tells you the assertions did not raise. It does not tell you they could.

## When to run this

- A test you just wrote or just refactored, before moving on.
- A test that has never been observed failing, including one inherited green from CI.
- Any suite described as guarding a contract, an invariant, or two implementations agreeing.
  These are the ones that go vacuous quietly, because the assertion is about shape rather
  than content.
- Before reporting "the tests pass" as evidence that a change works.

An assertion that compares derived collections is the highest-risk shape: sets of types,
sorted key lists, lengths, `is not None`. Two empty results satisfy most of them.

## The loop

1. **Pick the mutation.** The smallest change to the code under test that should trip this
   test, applied at the seam the test claims to guard. If the test says two strategies
   agree, break one strategy. If it says a parser rejects bad input, make the parser
   accept it.
2. **Run the suite** and read the output, not the exit code.
3. **Confirm the failure is the right one.** The test you are verifying is among the
   failures, and its message names the thing the test exists to protect. A test that fails
   with an import error or a fixture error has not been verified.
4. **Confirm the blast radius.** In a parametrised or multi-implementation suite, breaking
   implementation A must fail A's cases and leave B's passing. Wrong radius means the test
   is measuring something other than what its name says.
5. **Revert the mutation** and confirm the suite is green again. Always. A mutation left
   behind is a broken repository.

If the suite is unchanged by the mutation, the test is decorative. Fix the test, then run
this loop again on the fixed test.

## Choosing the mutation

Smallest, at the seam, one at a time.

- Stub a function to return an empty result, a constant, or `None`.
- Invert a single comparison or drop a single filter.
- Delete one branch of the behaviour the test names.

Do not mutate configuration, imports, or a shared base class to break a specific test.
Those produce failures everywhere and prove nothing about this test.

## When a surviving test is correct

Not every test that survives a mutation is decorative. A test can legitimately pass under
a break that is outside what it asserts. Stubbing a search function to return nothing
leaves `test_empty_query_returns_nothing` passing, and that is correct: the test asserts
emptiness, and emptiness is what it got. It would still fail if the function returned
something for an empty query, which is the failure it exists to catch.

The question is never "did this test survive" but "can this test fail for the reason it
exists". Verify a surviving test with a mutation aimed at its own claim.

## Anti-patterns

- **Mutating too broadly.** Breaking a shared import or renaming a fixture fails the whole
  suite and tells you nothing about the test in front of you.
- **Mutating the wrong layer.** Breaking the database when the test guards the parser
  produces a red run that is not evidence.
- **Reading the exit code only.** A non-zero exit with your test still passing means the
  test is decorative and something else caught the break.
- **Forgetting to revert.** Revert before you do anything else, and confirm green.
- **Treating every survivor as a defect.** See above.

## What to report

Name the mutation, the cases that failed, and the cases that did not:

> Stubbed `lexical.search` to return `[]`. Exactly 10 `[lexical]` cases failed, zero
> `[bm25]`. Reverted, suite green.

That is evidence. "50 tests pass" is not.
