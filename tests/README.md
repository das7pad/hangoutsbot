# Tests

The `hangupsbot` can be tested

- Run a syntax and lint check
  ```bash
  make lint
  ```

- Run the test suite
  ```bash
  make test-only
  ```

- Run the test suite with logging
  ```bash
  make test-only-verbose
  ```

- Run linting and the test suite
  ```bash
  make test
  ```


# Devs

Tests are done with `pytest` which supports *fixtures*.
Currently there are two fixtures implemented:

- `bot`

  a `HangupsBot` instance without a running `hangups.Client`

- `event`

  the fixture will be feed with different params to run:
  - within two different conversations
  - for two different users, an admin and a regular user

  the event can be feed with additional text:
  ```
  def my_test(event):
    event_with_text = event.with_text('my text')
    assert event_with_text.text == 'my text'
  ```
  it is also possible to prepend a default bot-command prefix:
  ```
  def my_test(event):
    event_with_args = event.for_command('my_cmd', 'first', 'second')
    assert event_with_args.text == '/bot my_cmd first second'
    args = event_with_args.args
    assert args[0] == 'first'
    assert args[1] == 'second'
  ```
