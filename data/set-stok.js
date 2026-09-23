const path = require('path');
const { PrismaMariaDb } = require(path.join(__dirname, '../server/node_modules/@prisma/adapter-mariadb'));
const { PrismaClient } = require(path.join(__dirname, '../server/node_modules/@prisma/client'));

const adapter = new PrismaMariaDb({
    host: 'localhost',
    port: 3306,
    user: 'root',
    password: 'root',
    database: 'sim_ritel',
});
const prisma = new PrismaClient({ adapter });

async function main() {
    const produkList = await prisma.produk.findMany();

    for (const produk of produkList) {
        // ambil rata-rata penjualan harian 7 hari terakhir produk ini
        const detail = await prisma.detail_penjualan.findMany({
            where: { produk_id: produk.id },
            include: { penjualan: true },
        });

        // urutkan by tanggal, ambil 7 hari terakhir
        const perHari = {};
        for (const d of detail) {
            const tgl = d.penjualan.tanggal.toISOString().slice(0, 10);
            perHari[tgl] = (perHari[tgl] || 0) + d.qty;
        }
        const tglTerurut = Object.keys(perHari).sort().slice(-7);
        const total7hari = tglTerurut.reduce((s, t) => s + perHari[t], 0);
        const rata7hari = tglTerurut.length > 0 ? total7hari / tglTerurut.length : 0;

        const stokAwal = Math.round(2 * produk.stok_minimum + rata7hari);

        await prisma.produk.update({
            where: { id: produk.id },
            data: { stok: stokAwal },
        });
        console.log(`${produk.nama}: stok awal = ${stokAwal}`);
    }
    console.log('=== STOK AWAL SELESAI DISET ===');
}

main()
    .catch((e) => { console.error('ERROR set stok:', e); process.exit(1); })
    .finally(() => prisma.$disconnect());