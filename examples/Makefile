
SRC = example_log.c
INCLUDE = -I../log_helper/include
LIBRARY = -L../log_helper/build/ -lLogHelper

EXEC = example

all: $(SRC)
	gcc example_log.c $(INCLUDE) $(LIBRARY) -o $(EXEC)

clean:
	rm $(EXEC)
