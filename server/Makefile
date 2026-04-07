CC ?= cc
CPPFLAGS += -D_POSIX_C_SOURCE=200809L
WARNINGS = -Wall -Wextra -Wshadow -Wstrict-prototypes -Wmissing-prototypes -Wformat=2 -Wwrite-strings
CFLAGS ?= -O2
CFLAGS += $(WARNINGS) $(CFLAGADD)

SERVER_SOURCES = server.c memory_map.c cmd_parse.c
SERVER_HEADERS = server.h memory_map.h cmd_parse.h protocol.h

.PHONY: all clean test

all: server rpdevmem

server: $(SERVER_SOURCES) $(SERVER_HEADERS)
	$(CC) $(CPPFLAGS) $(CFLAGS) -o $@ $(SERVER_SOURCES)

rpdevmem: rpdevmem.c memory_map.c memory_map.h protocol.h
	$(CC) $(CPPFLAGS) $(CFLAGS) -o $@ rpdevmem.c memory_map.c

test: test_cmd_parse test_protocol_layout
	./test_cmd_parse
	./test_protocol_layout

test_cmd_parse: tests/test_cmd_parse.c cmd_parse.c cmd_parse.h protocol.h
	$(CC) $(CPPFLAGS) $(CFLAGS) -I. -o $@ tests/test_cmd_parse.c cmd_parse.c

test_protocol_layout: tests/test_protocol_layout.c protocol.h
	$(CC) $(CPPFLAGS) $(CFLAGS) -I. -o $@ tests/test_protocol_layout.c

clean:
	rm -f server rpdevmem test_cmd_parse test_protocol_layout
