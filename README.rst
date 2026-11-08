Welcome to pyRofex's Documentation
===================================

Overview
--------
*pyRofex* is a python library that allows interactions with ROFEX's Rest and Websocket APIs.
An optional extra adds a market-data-only FIX client. It does not change the Rest or Websocket functions.

The library is designed to avoid developers hours of research and coding needed to connect with ROFEX APIs, so they could focused on the important part of their software.

Although, we recommend to take a look at the official `API documentation <https://apihub.primary.com.ar/assets/docs/Primary-API.pdf>`_ to get familiarize with the API Responses and functionality.


Warning
----------
pyRofex will only work with the websocket-client version between 0.54.0 and 0.57.0

Installing
----------
*pyRofex* is available at the `Python Package Index <https://pypi.org/project/pyrofex>`_ repository. Install and update using `pip <https://pip.pypa.io/en/stable/quickstart/>`_\ :

.. code-block:: python

   pip install -U pyRofex


API Credentials
---------------
In order to use the library you need to have the correct authentication credentials for the environment.

To get new credentials:

- **REMARKET**: go to `Remarket Website <https://remarkets.primary.ventures/>`_  and create an account for free.

- **LIVE**: contact MPI (Market and Platform Integration) team. (mail: mpi@primary.com.ar)

Dependencies
------------
- `requests <https://pypi.org/project/requests/>`_\: 2.20.0 or higher
- `simplejson <https://pypi.org/project/simplejson/>`_\: 3.10.0 or higher
- `enum34 <https://pypi.org/project/enum34/>`_\: 1.1.6 or higher
- `websocket-client <https://pypi.org/project/websocket_client/>`_\: Between 0.54.0 and 0.57.0

Optional, only for the FIX market-data client:

- `simplefix <https://pypi.org/project/simplefix/>`_\: 1.0.17 or higher (pure Python)
- `certifi <https://pypi.org/project/certifi/>`_\: CA bundle used when verifying TLS
- `tzdata <https://pypi.org/project/tzdata/>`_\: so the session-hours warning works on Windows

Features
--------
This sections describe the functionality and components of the library.

Available methods
^^^^^^^^^^^^^^^^^

Initialization
~~~~~~~~~~~~~~

Before you start using the library, you need to initialize the environment that you want to connect with.

Functions
"""""""""
* **initialize**: Initialize the specified environment. Set the default user, password and account for the environment.
* **set_default_environment**: Set default environment. The default environment that is going to be used when no environment is specified.

Rest
~~~~

The library provides functions to make requests to the REST API and return the corresponding response.

Functions
"""""""""

* **get_segments**\ : gets a list of valid segments.
* **get_instruments**\ : gets data of instruments by passing arguments for specific info.
* **get_all_instruments**\ : gets a list of all available instruments.
* **get_detailed_instruments**\ : gets a detailed list of all available instruments.
* **get_instrument_details**\ : gets the details of a single instrument.
* **get_market_data**\ : gets market data information for an instrument.
* **get_trade_history**\ : gets a list of historic trades for an instrument.
* **send_order**\ : sends a new order to the Market.
* **cancel_order**\ : cancels an order.
* **get_order_status**\ : gets the status of the specified order.
* **get_all_orders_status**\ : gets the status of all the orders associated with an account.

* **get_account_position**\ : gets the status of the account positions.
* **get_detailed_position**\ : gets the status of detailed account asset positions by asset type.
* **get_account_report**\ : gets the summary of associated account.

..

  *All functions return a dict of the JSON response.*


Websocket
~~~~~~~~~

The library allows users to start a connection to the websocket API. The connection will be monitored by a separated thread, so its very important to set the proper handlers to process new incoming messages.

Functions
"""""""""

* **init_websocket_connection**\ : configure the Websocket Client with the handlers and then start a Websocket connection with API.
* **close_websocket_connection**\ : close the connection with the API.
* **market_data_subscription**\ : sends a Market Data Subscription Message through the connection.
* **order_report_subscription**\ : sends an Order Report Subscription Message through the connection.
* **add_websocket_market_data_handler** \**: adds a new Market Data handler to the Websocket Client. This handler is going to be call when a new Market Data Message is received.
* **remove_websocket_market_data_handler** \**: removes a Market Data handler from the handlers list in the Websocket Client.
* **add_websocket_order_report_handler** \**: adds a new Order Report handler to the Websocket Client. This handler is going to be call when a new Order Report Message is received.
* **remove_websocket_order_report_handler** \**: removes an Order Report handler from the handlers list in the Websocket Client.
* **add_websocket_error_handler** \**: adds a new Error handler to the Websocket Client. This handler is going to be call when a new Error Message is received.
* **remove_websocket_error_handler** \**: removes an Error handler from the handlers list in the Websocket Client.
* **set_websocket_exception_handler**: sets an exception handler to the Websocket Client. This handler is going to be called when an Exception occurred in the client.
* **send_order_via_websocket**: sends a new order to the Market.
* **cancel_order_via_websocket**: cancels an order.

** **handlers** are pythons functions that will be call whenever the specific event occurred.

Enumerations
^^^^^^^^^^^^

The library also provides some enumerations to help developers avoid errors and improve readability. Next, you have the list of available enums:

* **Environment**: Identifies the environment to use. (REMARKET: Demo environment; LIVE: Production environment)
* **CFICode**: Identifies the type of instrument.
* **MarketDataEntry**: Identifies market data entries for an instrument.
* **Market**: Market ID associated to the instruments.
* **MarketSegment**: Market Segment ID associated to the instruments.
* **OrderType**: Identifies the different order types.
* **Side**\ : Identifies the side of an order.
* **TimeInForce**: Time modifier of the order that defines the time the order will be active.

How to use it
-------------

Once the library is install, we import and initialize it.

The initialization sets the user, password and account to the environment specified. Then, try to authenticate with the given user/password.

If the authentication fails, an ApiException is raised.

Finally, sets the environment as the default one. (you can change it with the set_default_environment function)

.. code-block:: python

   import pyRofex

   # Set the the parameter for the REMARKET environment
   pyRofex.initialize(user="sampleUser",
                      password="samplePassword",
                      account="sampleAccount",
                      environment=pyRofex.Environment.REMARKET)

   # In case you have a previously generated and active token, you will be able to do the following
   pyRofex.initialize(user="sampleUser",
                      password="samplePassword",
                      account="sampleAccount",
                      environment=pyRofex.Environment.REMARKET,
                      active_token="activeToken")


Rest
^^^^
.. code-block:: python

   # Makes a request to the Rest API and get the last price
   # Use the MarketDataEntry enum to specify the data
   pyRofex.get_market_data(ticker="DLR/DIC23",
                           entries=[pyRofex.MarketDataEntry.LAST])

   # Gets all segments
   pyRofex.get_segments()

   # Gets available instruments list
   pyRofex.get_all_instruments()

   # Alternative option to get all available instruments list
   pyRofex.get_instruments('all')

   # Alternative option to get instruments by given cfi code:
   pyRofex.get_instruments('by_cfi',
                           cfi_code=[pyRofex.CFICode.STOCK,
                                     pyRofex.CFICode.BOND,
                                     pyRofex.CFICode.CEDEAR])

   # Alternative option to get instruments by given segments
   pyRofex.get_instruments('by_segments',
                           market=pyRofex.Market.ROFEX,
                           market_segment=[pyRofex.MarketSegment.DDF,
                                           pyRofex.MarketSegment.MERV])

   # Gets detailed instruments list
   pyRofex.get_detailed_instruments()

   # Alternative option to get detailed instruments list
   pyRofex.get_instruments('details')

   # Get all order report for the configured account
   pyRofex.get_all_orders_status()

   # Gets historic trades
   pyRofex.get_trade_history(ticker="DLR/JUN23",
                             start_date="2018-12-01",
                             end_date="2019-01-10")

   # Sends a Limit order to the market
   order = pyRofex.send_order(ticker="DLR/DIC23",
                              side=pyRofex.Side.BUY,
                              size=10,
                              price=55.8,
                              order_type=pyRofex.OrderType.LIMIT)

   # Gets the last order status for the previous order
   pyRofex.get_order_status(order["order"]["clientId"])

   # Cancels the previous order
   cancel_order = pyRofex.cancel_order(order["order"]["clientId"])

   # Checks the order status of the cancellation order
   pyRofex.get_order_status(cancel_order["order"]["clientId"])

Websocket
^^^^^^^^^

.. code-block:: python

   # First we define the handlers that will process the messages and exceptions.
   def market_data_handler(message):
       print("Market Data Message Received: {0}".format(message))
   def order_report_handler(message):
       print("Order Report Message Received: {0}".format(message))
   def error_handler(message):
       print("Error Message Received: {0}".format(message))
   def exception_handler(e):
       print("Exception Occurred: {0}".format(e.message))

   # Initiate Websocket Connection
   pyRofex.init_websocket_connection(market_data_handler=market_data_handler,
                                     order_report_handler=order_report_handler,
                                     error_handler=error_handler,
                                     exception_handler=exception_handler)

   # Instruments list to subscribe
   instruments = ["DLR/DIC23", "DLR/ENE24"]
   # Uses the MarketDataEntry enum to define the entries we want to subscribe to
   entries = [pyRofex.MarketDataEntry.BIDS,
              pyRofex.MarketDataEntry.OFFERS,
              pyRofex.MarketDataEntry.LAST]

   # Subscribes to receive market data messages **
   pyRofex.market_data_subscription(tickers=instruments,
                                    entries=entries)

   # Subscribes to receive order report messages (default account will be used) **
   pyRofex.order_report_subscription()

** Every time a new message is received, the correct handler will be call.

FIX market data (optional)
--------------------------

This client reads Primary market data over FIX 5.0 SP2 (FIXT.1.1). It can send session messages and Market Data Request (``35=V``) only. It cannot send orders, cancels, or order-status requests.

Install the extra. The base install is unchanged, and ``import pyRofex`` does not load it:

.. code-block:: bash

   pip install "pyRofex[fix]"

``simplefix`` is pure Python, so the extra installs on Windows with Python 3.12 without a C++ toolchain. quickfix is not used.

The default host is the reMarkets demo, ``fix.remarkets.primary.com.ar:9876``. That port is TLS: community examples reach it by pointing stunnel at it in client mode. This client wraps the socket with ``ssl`` instead. Pass ``--host`` for any other endpoint, including production. There is no production default. Credentials are read from ``REMARKETS_FIX_USER`` and ``REMARKETS_FIX_PASSWORD``, or from ``--user`` and ``--password``. They are not stored in the library.

TLS verification is on by default. The trust store is certifi, or the PEM file passed with ``--cafile``. The demo server's chain does not validate that way. It sends an expired SHA-1 leaf ``CN=www.primary.com.ar`` (notAfter 2014-06-11, no subject alternative name for the FIX host), issued by Thawte SSL CA (notAfter 2020-02-07). The last certificate in the handshake is thawte Primary Root CA, which is signed by Thawte Premium Server CA and is not in certifi or a current Windows store. OpenSSL then reports ``unable to get local issuer certificate``. That is not fixed by installing certifi alone: the leaf is also expired, SHA-1, and named for a different host. When ``--cafile`` is omitted, a failed public check of this demo host is followed by a pin of that exact leaf (shipped as ``remarkets_demo_leaf.pem``). A different certificate is rejected. ``--cafile`` does not use the pin. ``--insecure`` skips both checks. ``--no-tls`` is for a local stunnel listener.

Primary's Rules of Engagement V2.0.20 list Market Data Request (``V``), Snapshot/Full Refresh (``W``), and Market Data Request Reject (``Y``). They do not list Incremental Refresh (``X``). ``MDUpdateType`` is only ``0 = Full Refresh``, and the "snapshot + updates" flow is a stream of ``W`` messages. Unsubscribe is another ``V`` with ``SubscriptionRequestType=2`` and the same ``MDReqID``. If an ``X`` frame does arrive, it is parsed, but that behavior is not in the ROE.

Tag 7201 is exposed as ``trade_side`` with values ``BUY``, ``SELL``, or ``None`` (``null`` in the JSONL file). The ROE calls it "Side of the trade". It is not an aggressor flag. A missing 7201 stays ``None``; bid/offer type and tag 54 are not used to fill it. ``trade_condition`` (tag 277, ``U`` = Exchange Last) and ``trd_type`` (tag 828) are kept. Exchange Last can be repeated on a later snapshot when no new trade has occurred. Tags 288 and 289, when the demo sends them, are kept as ``md_entry_buyer`` and ``md_entry_seller`` and are not a side. Every received tag is kept, including tags this client does not name.

``35=h`` TradingSessionStatus is not a market-data entry. The demo sends a burst of unsolicited ones after the snapshot. They are written to the JSONL like any other inbound message and do not change the subscription or the sequence handling.

Session hours in the ROE are 09:00-19:00. The client treats that as America/Argentina/Buenos_Aires and only warns outside the window. Only one FIX session may exist at a time for the same CompIDs. Reconnect is off unless ``--reconnect`` is set. A Resend Request is sent at most once for an inbound gap; market data is not replayed.

CLI, listening for two minutes and writing one JSON object per inbound message (``received_at`` is local time, ``raw`` is the FIX frame with SOH as ``\u0001``, ``parsed`` is the decoded message).

On Windows ``cmd``:

.. code-block:: bat

   set REMARKETS_FIX_USER=your-user
   set REMARKETS_FIX_PASSWORD=your-password
   python -m pyRofex.fix_md --symbol DLR/NOV26 --entries BI,OF,LA --depth 5 --seconds 120 --out file.jsonl

On a Unix shell, ``export`` the same two variables and run the same ``python -m pyRofex.fix_md`` command.

Library use:

.. code-block:: python

   import os
   from pyRofex.fix import FixMarketDataClient

   client = FixMarketDataClient(
       os.environ["REMARKETS_FIX_USER"],
       os.environ["REMARKETS_FIX_PASSWORD"],
   )
   client.connect()
   client.subscribe("DLR/NOV26", ["BI", "OF", "LA"], depth=5, updates=True)
   client.run(120, on_message=print)
   client.logout()

A Windows / Python 3.12 smoke test of the demo (before the pin was added) logged on only with ``--insecure``. Without it, TLS failed with ``CERTIFICATE_VERIFY_FAILED`` / ``unable to get local issuer certificate``, and that ``ssl.SSLError`` was reported as ``could not write ...jsonl`` because it is an ``OSError`` raised from ``connect`` inside the file ``with`` block. Connect and TLS failures are now separate messages from output-file failures. The same smoke test, once the TLS check was skipped, showed this session and then a clean Logout (``35=5``):

- Logon from the server
- one ``35=W`` snapshot
- on the order of 50 unsolicited ``35=h`` TradingSessionStatus messages
- heartbeats, including a Test Request echo ``112=TR1``

The snapshot had ``268=3``. The bid and offer were empty-book placeholders with only ``290=0`` (no price and no size). The trade entry was ``269=2`` with tags 270, 271, 272, 273, ``277=U``, ``288=*``, ``289=*``, and ``7201=1``. It did not include 828 or 54. ``7201=1`` is ``trade_side=BUY`` for that one trade. That is a single observation, not a guarantee that every DLR future print carries 7201. The offline fixture uses that tag set; the username is replaced, and the numeric price, size, and clock fields are stand-ins because the live digits were not copied out. ``288`` and ``289`` are the literal asterisks from the sanitized report.

Repeat the smoke test between 09:00 and 19:00 Buenos Aires time, with no other FIX session logged on as that user. Do not pass ``--insecure`` unless you intend to skip both the CA check and the demo pin. If Logon is rejected because the acceptor kept the previous sequence, retry once with ``--reset-seq-num`` (tag 141, which the ROE does not list).

What is checked offline: Logon and Market Data Request encoding, checksum and body length, the sanitized demo snapshot (empty book, 7201 present, 288/289 kept, no 828 or 54), a burst of ``35=h``, Test Request id ``TR1`` and its echo, Logout, a single Resend Request, the demo leaf pin, and CLI messages that distinguish TLS errors, connection errors, and file errors. Those tests do not open a network connection. The certificate chain above was read with a TLS handshake only; no FIX Logon was sent from this environment.

Still not established from one snapshot: whether 7201 is populated on later trades or on other symbols, whether ``EV`` corresponds to cash volume (``269=w``), and whether a second connection needs tag 141. ``IV``, ``ACP``, and ``TC`` are not MDEntryType values in the ROE, so the client rejects them.

Official API Documentation
==========================

For more detailed information about ROFEX Rest and Websocket APIs go to the `Primary API Documentation <https://apihub.primary.com.ar/assets/docs/Primary-API.pdf>`_.

Acknowledgements
================

Development of this software was driven by
`Primary <https://www.primary.com.ar/>`_ as part of an Open Source
initiative of `Grupo Rofex <https://www.rofex.com.ar/>`_.

Author/Maintainer
-----------------

* `Franco Zanuso <https://github.com/fzanuso>`_
