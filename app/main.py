import asyncio

from .browser import BrowserManager
from .controller import AccountController
from .monitor import AccountMonitor
from .telegram import TelegramBot


async def main():
    browser = BrowserManager()
    telegram = TelegramBot()

    await browser.start()

    controller = AccountController(
        browser=browser,
        telegram=telegram,
    )

    controller.connect_commands()

    telegram.build()

    monitor = AccountMonitor(
        browser=browser,
        controller=controller,
    )

    try:
        await telegram.start()
        await monitor.start_all()

        print("Rooter Auto Buyer started.")

        while True:
            await asyncio.sleep(3600)

    except KeyboardInterrupt:
        pass

    finally:
        await monitor.stop_all()
        await telegram.stop()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
