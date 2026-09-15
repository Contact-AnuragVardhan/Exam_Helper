from __future__ import annotations

from services.logger import get_logger
from terminal.teacher_terminal import run_teacher_terminal


def main() -> None:
    log = get_logger("app")
    log.info("Exam Helper teacher terminal startup")
    run_teacher_terminal()


if __name__ == "__main__":
    main()
