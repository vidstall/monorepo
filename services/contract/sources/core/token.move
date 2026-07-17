module dvconf::token {
    use sui::coin::{Self, Coin, TreasuryCap};

    /// One-time witness — must be uppercase of module name
    public struct TOKEN has drop {}

    fun init(witness: TOKEN, ctx: &mut TxContext) {
        let (treasury_cap, metadata) = coin::create_currency(
            witness,
            9,
            b"DVCONF",
            b"DVConf Token",
            b"Economic incentive token for the DVConf decentralized video conference network",
            option::none(),
            ctx
        );

        transfer::public_freeze_object(metadata);
        transfer::public_transfer(treasury_cap, ctx.sender());
    }

    public fun mint(
        cap: &mut TreasuryCap<TOKEN>,
        amount: u64,
        recipient: address,
        ctx: &mut TxContext
    ) {
        coin::mint_and_transfer(cap, amount, recipient, ctx);
    }

    public fun burn(
        cap: &mut TreasuryCap<TOKEN>,
        coin: Coin<TOKEN>
    ) {
        coin::burn(cap, coin);
    }

    #[test_only]
    public fun init_for_testing(ctx: &mut TxContext) {
        init(TOKEN {}, ctx);
    }
}
