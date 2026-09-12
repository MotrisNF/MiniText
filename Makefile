PREFIX ?= $(HOME)/.local
BINDIR ?= $(PREFIX)/bin
LIBDIR ?= $(PREFIX)/share/mini

.PHONY: install uninstall

install:
	./install.sh "$(LIBDIR)" "$(BINDIR)"

uninstall:
	./install.sh --uninstall "$(LIBDIR)" "$(BINDIR)"
