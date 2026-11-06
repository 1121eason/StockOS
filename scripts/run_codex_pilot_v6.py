"""Execute one PromptSetV6 Q2 pilot through the shared receipt and preservation gates."""

import run_codex_pilot_v5 as runner

EXPECTED_PROMPT_VERSION = "PromptSetV6"


def main(argv=None):
    return runner.main(
        argv,
        expected_prompt_version=EXPECTED_PROMPT_VERSION,
        purpose="codex_pit_q2_v6_pilot",
        activation="single_quarter_pilot_v6",
    )


if __name__ == "__main__":
    main()
