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
  ```python
  def my_test(event):
    event_with_text = event.with_text('my text')
    assert event_with_text.text == 'my text'
  ```
  it is also possible to prepend a default bot-command prefix:
  ```python
  def my_test(event):
    event_with_args = event.for_command('my_cmd', 'first', 'second')
    assert event_with_args.text == '/bot my_cmd first second'
    args = event_with_args.args
    assert args[0] == 'first'
    assert args[1] == 'second'
  ```

## Plugin tests may use the following structure
  ```python
  import pytest

  from hangupsbot import plugins
  from hangupsbot import commands

  from tests import run_cmd

  @pytest.mark.asyncio
  async def test_load_plugin(bot):
      await plugins.load(bot, 'plugins.my_plugin')

  @pytest.mark.asyncio
  async def test_my_command(bot, event):
      event = event.for_command('my_command', 'INVALID-ARGUMENT')
      with pytest.raises(commands.Help):
          await run_cmd(bot, event)

      event = event.for_command('my_command', 'additional arguments')
      result = await run_cmd(bot, event)
      expected_text = '<b>Changed entry XYZ</b>'
      assert expected == result
  ```

### Test a plugin which sends messages

  Commands can return their command output, this simplifies the test setup as
  seen above.

  Command output that was sent using `bot.coro_send_message` can be
  retrieved from `bot.last_message`. The returned object is a
  `tests.utils.Message`, which has a simple api:

  - `conv_id`: `str`, the target conversation
  - `text`: `str` or `list[ChatMessageSegment]`, the message content
  - `context`: `dict`, additional information about the message
  - `image_id`: `int`, upload id of an image
