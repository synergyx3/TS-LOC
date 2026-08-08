from . import __version__


def main() -> None:
    print(f"TS-Local {__version__} — foundation build")
    print("Execution mode defaults to DRY_RUN until a live broker is explicitly configured.")


if __name__ == "__main__":
    main()
