# Database Systems Concepts, Schemas, & Transactions

## 1. Relational Model & Schema Definitions
A relational database schema S is defined by a set of relation schemas R1, R2, ..., Rn and a set of integrity constraints. A relation schema R(A1, A2, ..., An) is made up of a relation name R and a list of attributes A. Each attribute Ai is the name of a role played by some domain D in the relation schema R. A candidate key is a minimal superkey of relation schema R such that no proper subset is a superkey. Every relation schema must possess at least one primary key chosen from the candidate keys to guarantee entity integrity.

## 2. Referential Integrity & Foreign Key Constraints
Referential integrity constraints specify relationships between tuples in two relations: the referencing relation and the referenced relation. A set of attributes FK in relation schema R1 is a foreign key of R1 that references relation R2 if the attributes in FK have the same domain as the primary key PK of R2, and for any tuple t1 in R1, either t1[FK] is null or matches the primary key value t2[PK] of some tuple t2 in R2. Foreign keys prevent dangling references and maintain consistency across normalized entity boundaries.

## 3. Indexing Structures: B+ Trees & Hash Indices
A B+ Tree is a self-balancing tree data structure that maintains sorted data and allows searches, sequential access, insertions, and deletions in logarithmic time O(log N). In a B+ tree of order p, internal nodes guide search queries while all actual data pointers reside exclusively in the leaf nodes. Leaf nodes are linked sequentially via pointers to facilitate high-throughput range scans. Hash indexes provide O(1) point lookups based on an exact hash function but cannot support range queries.

## 4. ACID Properties & Transaction Lifecycle
A database transaction is a logical unit of work that must satisfy ACID properties: Atomicity guarantees all operations succeed or all are rolled back; Consistency guarantees database transitions only between valid states satisfying all invariants; Isolation guarantees concurrent transactions execute without interference as if serially; Durability guarantees committed changes survive system crashes or power failures via write-ahead logging.

## 5. Concurrency Control: Two-Phase Locking (2PL) & MVCC
Two-Phase Locking (2PL) is a concurrency control protocol guaranteeing serializability. A transaction is divided into an expanding growing phase where locks are acquired and no locks are released, and a shrinking phase where locks are released and no new locks can be acquired. Strict 2PL holds exclusive write locks until transaction commit or abort to prevent cascading aborts. Modern high-concurrency databases utilize Multi-Version Concurrency Control (MVCC) where readers never block writers and writers never block readers by maintaining snapshot version chains.

## 6. Database Normalization & Functional Dependencies
Normalization decomposes relations with anomalies to produce smaller, well-structured relations. First Normal Form (1NF) disallows multivalued and composite attributes. Second Normal Form (2NF) requires 1NF and that every non-prime attribute is fully functionally dependent on the entire primary key. Third Normal Form (3NF) requires 2NF and eliminates transitive dependencies. Boyce-Codd Normal Form (BCNF) strictly requires that for every functional dependency X -> Y, X must be a superkey.

## 7. Write-Ahead Logging (WAL) & ARIES Crash Recovery
Write-Ahead Logging (WAL) ensures durability and atomicity by requiring that any log record describing an update must be flushed to non-volatile disk storage before the corresponding dirty data page is written to disk. The ARIES recovery algorithm operates in three distinct phases following a crash: 1) Analysis phase scans log forward to identify dirty pages and active transactions; 2) Redo phase repeats history from the smallest unwritten LSN to restore state; 3) Undo phase rolls back active transactions backwards to clean uncommitted states.

## 8. Distributed Storage, Sharding & The CAP Theorem
Distributed database architectures partition data across multiple cluster nodes via range-based, hash-based, or directory-based sharding. The CAP theorem states that a distributed data store can simultaneously provide at most two of three guarantees: Consistency (every read receives the most recent write or an error), Availability (every non-failing node returns a non-error response without guarantee of latest write), and Partition Tolerance (system continues operating despite arbitrary packet loss or network partitioning).
