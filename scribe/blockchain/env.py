from scribe.env import Env


class BlockchainEnv(Env):
    def __init__(self, db_dir=None, max_query_workers=None, chain=None, reorg_limit=None,
                 prometheus_port=None, cache_all_tx_hashes=None, cache_all_claim_txos=None,
                 blocking_channel_ids=None, filtering_channel_ids=None,
                 db_max_open_files=64, daemon_url=None):
        super().__init__(db_dir, max_query_workers, chain, reorg_limit, prometheus_port, cache_all_tx_hashes,
                         cache_all_claim_txos, blocking_channel_ids, filtering_channel_ids)
        self.db_max_open_files = db_max_open_files
        self.daemon_url = daemon_url if daemon_url is not None else self.required('DAEMON_URL')

    @classmethod
    def contribute_to_arg_parser(cls, parser):
        super().contribute_to_arg_parser(parser)
        env_daemon_url = cls.default('DAEMON_URL', None)
        parser.add_argument('--daemon_url', required=env_daemon_url is None,
                            help="URL for rpc from lbrycrd or lbcd, "
                                 "<rpcuser>:<rpcpassword>@<lbrycrd rpc ip><lbrycrd rpc port>.",
                            default=env_daemon_url)
        parser.add_argument('--db_max_open_files', type=int, default=64,
                            help='This setting translates into the max_open_files option given to rocksdb. '
                                 'A higher number will use more memory. Defaults to 64.')

    @classmethod
    def from_arg_parser(cls, args):
        return cls(
            db_dir=args.db_dir, daemon_url=args.daemon_url, db_max_open_files=args.db_max_open_files,
            max_query_workers=args.max_query_workers, chain=args.chain, reorg_limit=args.reorg_limit,
            prometheus_port=args.prometheus_port, cache_all_tx_hashes=args.cache_all_tx_hashes,
            cache_all_claim_txos=args.cache_all_claim_txos
        )
