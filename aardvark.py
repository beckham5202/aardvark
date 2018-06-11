#!/usr/bin/env python4

# This is the basic aaalgo tensorflow model training framework.
import errno
import os
from abc import ABC, abstractmethod
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
# C++ code, python3 setup.py build
import time, datetime
import logging
import simplejson as json
from tqdm import tqdm
import numpy as np
import tensorflow as tf
import picpac
import __main__

flags = tf.app.flags
FLAGS = flags.FLAGS

flags.DEFINE_integer('classes', 2, 'number of classes')
flags.DEFINE_bool('dice', None, 'use dice loss for segmentation')
# PicPac-related parameters
flags.DEFINE_string('db', None, 'training db')
flags.DEFINE_string('val_db', None, 'validation db')

flags.DEFINE_string('mixin', None, 'db to be mixed into training')
flags.DEFINE_integer('channels', 3, 'image channels')
flags.DEFINE_boolean('cache', True, 'cache images in memory') # cache small db in memory
flags.DEFINE_string('augments', 'augments.json', 'augment config file')
flags.DEFINE_string('colorspace', 'RGB', 'colorspace')
flags.DEFINE_integer('picpac_dump', 20, 'dump training example for debugging')

flags.DEFINE_integer('batch', 1, 'batch size')

flags.DEFINE_integer('max_size', 200000, 'max image size') 
flags.DEFINE_integer('fix_width', 0, '')
flags.DEFINE_integer('fix_height', 0, '')

flags.DEFINE_integer('clip_stride', 16, '')
flags.DEFINE_integer('clip_shift', 0, '')

# model saving parameters
flags.DEFINE_string('model', 'model', 'model directory')
flags.DEFINE_string('resume', None, 'resume training from this model')
flags.DEFINE_integer('max_to_keep', 100, 'models to keep')
flags.DEFINE_integer('epoch_steps', None, 'by default all images')
flags.DEFINE_integer('max_epochs', 500, '')
flags.DEFINE_integer('ckpt_epochs', 10, '')
flags.DEFINE_integer('val_epochs', 10, '')

# optimizer settings
flags.DEFINE_float('lr', 0.01, 'Initial learning rate.')
flags.DEFINE_float('decay_rate', 0.95, '')
flags.DEFINE_float('decay_steps', 500, '')
flags.DEFINE_boolean('adam', True, '')


def load_augments (is_training):
    augments = []
    if is_training:
        if FLAGS.augments:
            with open(FLAGS.augments, 'r') as f:
                augments = json.loads(f.read())
            print("Using augments:")
            print(json.dumps(augments))
            pass
        pass
    return augments

def create_picpac_stream (path, is_training, extra_config):

    assert os.path.exists(path)
    print("CACHE:", FLAGS.cache)
    # check db size, warn not to cache if file is big
    statinfo = os.stat(path)
    if statinfo.st_size > 0x40000000 and FLAGS.cache:
        print_red("DB is probably too big too be cached, consider adding --cache 0")

    config = {"db": path,
              "loop": is_training,
              "shuffle": is_training,
              "reshuffle": is_training,
              "annotate": [],
              "channels": FLAGS.channels,
              "stratify": is_training,
              "dtype": "float32",
              "batch": FLAGS.batch,
              "colorspace": FLAGS.colorspace,
              "cache": FLAGS.cache,
              "transforms": []
             }

    if is_training:
        config["dump"] = FLAGS.picpac_dump # dump 20 training samples for debugging and see

    if is_training and not FLAGS.mixin is None:
        print("mixin support is incomplete in new picpac.")
        assert os.path.exists(FLAGS.mixin)
        config['mixin'] = FLAGS.mixin
        config['mixin_group_reset'] = 0
        config['mixin_group_delta'] = 1
        pass
    config.update(extra_config)
    return picpac.ImageStream(config)

class Model(ABC):

    def __init__ (self):
        # build model here
        super().__init__()
        self.metrics = []
        self.variables_to_train = None

    @abstractmethod
    def build_graph (self):
        pass

    def init_session (self, sess):
        pass

    def extra_stream_config (self, is_training):
        return {}

    @abstractmethod
    def feed_dict (self, record):
        pass
    pass

class ClassificationModel(Model):

    def __init__ (self):
        super().__init__()
        pass

    @abstractmethod
    def inference (self, images, classes, is_training):
        pass

    def build_graph (self):
        is_training = tf.placeholder(tf.bool, name="is_training")
        images = tf.placeholder(tf.float32, shape=(None, None, None, FLAGS.channels), name="images")
        labels = tf.placeholder(tf.int32, shape=(None,))

        self.is_training = is_training
        self.images = images
        self.labels = labels

        logits = tf.identity(self.inference(images, FLAGS.classes, is_training), name='logits')
        probs = tf.nn.softmax(logits, name='probs')
        prob = tf.squeeze(tf.slice(tf.nn.softmax(logits), [0,1], [-1,1]), 1, name='prob')
        # cross-entropy
        xe = tf.nn.sparse_softmax_cross_entropy_with_logits(logits=logits, labels=labels)
        xe = tf.reduce_mean(xe, name='xe')
        # accuracy
        acc = tf.cast(tf.nn.in_top_k(logits, labels, 1), tf.float32)
        acc = tf.reduce_mean(acc, name='ac')
        # loss
        tf.losses.add_loss(xe)
        self.metrics.extend([xe, acc])
        pass

    def extra_stream_config (self, is_training):
        augments = load_augments(is_training)
        shift = 0
        if is_training:
            shift = FLAGS.clip_shift
        return {"transforms": [
                  {"type": "resize", "max_size": FLAGS.max_size},
                  ] + augments + [
                      {"type": "clip", "shift": shift, "width": FLAGS.fix_width, "height": FLAGS.fix_height, "round": FLAGS.clip_stride, "border_type": "replicate"},
                  ]
             }

    def feed_dict (self, record, is_training = True):
        # load picpac record into feed_dict
        meta, images = record
        return {self.is_training: is_training,
                self.images: images,
                self.labels: meta.labels}
    pass

class SegmentationModel(Model):

    def __init__ (self):
        super().__init__()
        pass

    @staticmethod
    def dice_loss (gt, prob):
        return -2 * (tf.reduce_sum(gt * prob) + 0.00001) / (tf.reduce_sum(gt) + tf.reduce_sum(prob) + 0.00001)

    @abstractmethod
    def inference (self, images, is_training):
        pass

    def build_graph (self):
        is_training = tf.placeholder(tf.bool, name="is_training")
        images = tf.placeholder(tf.float32, shape=(None, None, None, FLAGS.channels), name="images")
        labels = tf.placeholder(tf.int32, shape=(None, None, None, 1))

        self.is_training = is_training
        self.images = images
        self.labels = labels

        if FLAGS.dice:
            assert FLAGS.classes == 2
            logits = self.inference(images, 1, is_training)
            probs = tf.sigmoid(logits)
            prob = tf.squeeze(probs, 3, name='prob')

            labels = tf.squeeze(labels, axis=3)  # [?,?,?,1] -> [?,?,?], picpac generates 4-D tensor
            dice = tf.identity(dice_loss(tf.cast(labels, df.float32), prob), name='di')
            tf.losses.add_loss(dice)
            self.metrics.append(dice)
        else:
            logits = tf.identity(self.inference(images, FLAGS.classes, is_training), name='logits')
            probs = tf.nn.softmax(logits, name='probs')
            prob = tf.squeeze(tf.slice(probs, [0,0,0,1], [-1,-1,-1,1]), 3, name='prob')
            # setup loss
            logits1 = tf.reshape(logits, (-1, FLAGS.classes))
            labels1 = tf.reshape(labels, (-1,))
            # cross-entropy
            xe = tf.nn.sparse_softmax_cross_entropy_with_logits(logits=logits1, labels=labels1)
            xe = tf.reduce_mean(xe, name='xe')
            # accuracy
            acc = tf.cast(tf.nn.in_top_k(logits1, labels1, 1), tf.float32)
            acc = tf.reduce_mean(acc, name='acc')
            tf.losses.add_loss(xe)
            self.metrics.extend([xe, acc])
        pass

    def extra_stream_config (self, is_training):
        augments = load_augments(is_training)
        shift = 0
        if is_training:
            shift = FLAGS.clip_shift
        return {"annotate": [1],
                "transforms": [
                  {"type": "resize", "max_size": FLAGS.max_size},
                  ] + augments + [
                  {"type": "clip", "shift": shift, "width": FLAGS.fix_width, "height": FLAGS.fix_height, "round": FLAGS.clip_stride},
                  {"type": "rasterize"},
                  ]
               }

    def feed_dict (self, record, is_training = True):
        # load picpac record into feed_dict
        _, images, labels = record
        return {self.is_training: is_training,
                self.images: images,
                self.labels: labels}
    pass

class Metrics:  # display metrics
    def __init__ (self, model):
        self.metric_names = [x.name[:-2] for x in model.metrics]
        self.cnt, self.sum = 0, np.array([0] * len(model.metrics), dtype=np.float32)
        pass

    def update (self, mm, cc):
        self.sum += np.array(mm) * cc
        self.cnt += cc
        self.avg = self.sum / self.cnt
        return ' '.join(['%s=%.3f' % (a, b) for a, b in zip(self.metric_names, list(self.avg))])

def train (model):

    bname = os.path.splitext(os.path.basename(__main__.__file__))[0]
    logging.basicConfig(filename='%s-%s.log' % (bname, datetime.datetime.now().strftime('%Y%m%d-%H%M%S')),level=logging.DEBUG, format='%(asctime)s %(message)s')

    model.build_graph()

    if FLAGS.model:
        try:    # create directory if not exists
            os.makedirs(FLAGS.model)
        except OSError as exc:
            if exc.errno != errno.EEXIST:
                raise
            pass

    global_step = tf.train.create_global_step()
    LR = tf.train.exponential_decay(FLAGS.lr, global_step, FLAGS.decay_steps, FLAGS.decay_rate, staircase=True)
    if FLAGS.adam:
        print("Using Adam optimizer, reducing LR by 100x")
        optimizer = tf.train.AdamOptimizer(LR/100)
    else:
        optimizer = tf.train.MomentumOptimizer(learning_rate=LR, momentum=0.9)

    metrics = model.metrics
    reg_losses = tf.losses.get_regularization_losses()
    if len(reg_losses) > 0:
        reg_loss = tf.add_n(reg_losses, name='l2')
        metrics.append(reg_loss)
    for loss in tf.losses.get_losses():
        print("LOSS:", loss.name)
    total_loss = tf.losses.get_total_loss(name='L')
    metrics.append(total_loss)

    train_op = tf.contrib.training.create_train_op(total_loss, optimizer, global_step=global_step, variables_to_train=model.variables_to_train)
    saver = tf.train.Saver(max_to_keep=FLAGS.max_to_keep)

    stream = create_picpac_stream(FLAGS.db, True, model.extra_stream_config(True))
    # load validation db
    val_stream = None
    if FLAGS.val_db:
        val_stream = create_picpac_stream(FLAGS.val_db, False, model.extra_stream_config(False))

    epoch_steps = FLAGS.epoch_steps
    if epoch_steps is None:
        epoch_steps = (stream.size() + FLAGS.batch-1) // FLAGS.batch
    best = 0

    ss_config = tf.ConfigProto()
    ss_config.gpu_options.allow_growth=True

    with tf.Session(config=ss_config) as sess:
        sess.run(tf.global_variables_initializer())
        sess.run(tf.local_variables_initializer())
        model.init_session(sess)
        if FLAGS.resume:
            saver.restore(sess, FLAGS.resume)

        global_start_time = time.time()
        epoch, step = 0, 0

        while epoch < FLAGS.max_epochs:
            start_time = time.time()
            metrics = Metrics(model)
            progress = tqdm(range(epoch_steps), leave=False)
            for _ in progress:
                record = stream.next()
                mm, _ = sess.run([model.metrics, train_op], feed_dict=model.feed_dict(record, True))
                metrics_txt = metrics.update(mm, record[1].shape[0])
                progress.set_description(metrics_txt)
                step += 1
                pass
            stop = time.time()
            msg = 'train epoch=%d step=%d %s elapsed=%.3f time=%.3f' % (
                        epoch, step, metrics_txt, stop - global_start_time, stop - start_time)
            print_green(msg)
            logging.info(msg)

            epoch += 1

            if (epoch % FLAGS.val_epochs == 0) and val_stream:
                lr = sess.run(LR)
                # evaluation
                metrics = Metrics(model)
                val_stream.reset()
                progress = tqdm(val_stream, leave=False)
                for record in progress:
                    mm = sess.run(model.metrics, feed_dict=model.feed_dict(record, False))
                    metrics_txt = metrics.update(mm, record[1].shape[0])
                    progress.set_description(metrics_txt)
                    pass
                if metrics.avg[-1] > best:
                    best = metrics.avg[-1]
                msg = 'valid epoch=%d step=%d %s lr=%.4f best=%.3f' % (
                            epoch-1, step, metrics_txt, lr, best)
                print_red(msg)
                logging.info(msg)
            # model saving
            if (epoch % FLAGS.ckpt_epochs == 0) and FLAGS.model:
                ckpt_path = '%s/%d' % (FLAGS.model, epoch)
                saver.save(sess, ckpt_path)
                print('saved to %s.' % ckpt_path)
            pass
        pass
    pass

def print_red (txt):
    print('\033[91m' + txt + '\033[0m')

def print_green (txt):
    print('\033[92m' + txt + '\033[0m')

