import argparse
import asyncio
import logging
import sys

from tbas.tbas import Interpreter


async def stdio_reader(*args, **kwargs):
    sys.stdin.flush()
    return sys.stdin.read(*args, **kwargs)


async def stdio_writer(*args, **kwargs):
    return sys.stdout.write(*args, **kwargs)


async def run_tbas(program, **kwargs):
    i = Interpreter(**kwargs)
    future = asyncio.ensure_future(i.run(program))
    await future
    return future.result()


def main():
    p = argparse.ArgumentParser(description='tbas')
 
    m = p.add_mutually_exclusive_group()
    m.add_argument('-c', action='store_true', help='attach console to STD*')
    m.add_argument('-m', action='store_true', help='attach modem to STD*')
    p.add_argument('-d', '--debug', action='store_true')
    p.add_argument('-f', type=int, help='print contents of frame')

    p.add_argument('program')
    args = p.parse_args()

    if args.debug:
        logging.basicConfig(level=logging.DEBUG)

    kwargs = {}

    if args.c:
        kwargs.update({
            'console_read': stdio_reader,
            'console_write': stdio_writer
            })

    elif args.m:
        kwargs.update({
            'modem_read': stdio_reader,
            'modem_write': stdio_writer
            })

    loop = asyncio.get_event_loop()
    context = loop.run_until_complete(run_tbas(args.program, **kwargs))
    print("\n")

    if args.f:
        print(context.stack[args.f].format_mcell('03d'))


if __name__ == '__main__':
    main()
