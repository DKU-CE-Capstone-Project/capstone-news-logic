"""Compatibility entry point; edit capstone_news_logic/gdelt.py for shared logic."""
from capstone_news_logic.gdelt import *  # noqa: F401,F403

if __name__ == "__main__":
    main(sys.argv[1:])
