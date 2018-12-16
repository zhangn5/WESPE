import torch
import torch.nn as nn
import torch.optim as optim

from generator import Generator
from discriminator import Discriminator
from utils import gradient_penalty, GaussianBlur, GrayLayer, ContentLoss, TVLoss


class WESPE:

    def __init__(self, image_size, use_pretrained_generator=False):

        self.generator_g = Generator().cuda()
        self.generator_f = Generator().cuda()
        self.discriminator_c = Discriminator(
            image_size, num_input_channels=3,
            use_spectral_normalization=True
        ).cuda()
        self.discriminator_t = Discriminator(
            image_size, num_input_channels=1,
            use_spectral_normalization=True
        ).cuda()

        if use_pretrained_generator:
            self.generator_g.load_state_dict(torch.load('models/pretrained_generator.pth'))
            self.generator_f.load_state_dict(torch.load('models/pretrained_generator.pth'))

        self.content_criterion = ContentLoss().cuda()
        self.tv_criterion = TVLoss().cuda()
        self.color_criterion = nn.BCEWithLogitsLoss().cuda()
        self.texture_criterion = nn.BCEWithLogitsLoss().cuda()

        self.g_optimizer = optim.Adam(lr=5e-4, params=self.generator_g.parameters())
        self.f_optimizer = optim.Adam(lr=5e-4, params=self.generator_f.parameters())
        self.c_optimizer = optim.Adam(lr=3e-5, params=self.discriminator_c.parameters())
        self.t_optimizer = optim.Adam(lr=3e-5, params=self.discriminator_t.parameters())

        self.blur = GaussianBlur().cuda()
        self.gray = GrayLayer().cuda()

    def train_step(self, x, y):

        y_fake = self.generator_g(x)
        x_fake = self.generator_f(y_fake)

        for p in self.discriminator_c.parameters():
            p.requires_grad = False
        for p in self.discriminator_t.parameters():
            p.requires_grad = False

        content_loss = self.content_criterion(x, x_fake)
        tv_loss = self.tv_criterion(y_fake)

        batch_size = x.size(0)
        pos_labels = torch.ones(batch_size, dtype=torch.float, device=x.device)
        neg_labels = torch.zeros(batch_size, dtype=torch.float, device=x.device)

        y_fake_blur = self.blur(y_fake)
        color_generation_loss = self.color_criterion(self.discriminator_c(y_fake_blur), pos_labels)
        y_fake_gray = self.gray(y_fake)
        texture_generation_loss = self.texture_criterion(self.discriminator_t(y_fake_gray), pos_labels)

        generator_loss = content_loss + 100.0 * tv_loss
        generator_loss += 5e-3 * (color_generation_loss + texture_generation_loss)

        self.g_optimizer.zero_grad()
        self.f_optimizer.zero_grad()
        generator_loss.backward()
        self.g_optimizer.step()
        self.f_optimizer.step()

        for p in self.discriminator_c.parameters():
            p.requires_grad = True
        for p in self.discriminator_t.parameters():
            p.requires_grad = True

        y_real_blur = self.blur(y)
        y_real_gray = self.gray(y)

        color_discriminator_loss = self.color_criterion(self.discriminator_c(y_real_blur), pos_labels) \
            + self.color_criterion(self.discriminator_c(y_fake_blur.detach()), neg_labels)

        texture_discriminator_loss = self.texture_criterion(self.discriminator_t(y_real_gray), pos_labels) \
            + self.texture_criterion(self.discriminator_t(y_fake_gray.detach()), neg_labels)

        # gp1 = gradient_penalty(y_real_blur, y_fake_blur.detach(), self.discriminator_c)
        # gp2 = gradient_penalty(y_real_gray, y_fake_gray.detach(), self.discriminator_t)

        discriminator_loss = color_discriminator_loss + texture_discriminator_loss

        self.c_optimizer.zero_grad()
        self.t_optimizer.zero_grad()
        discriminator_loss.backward()
        self.c_optimizer.step()
        self.t_optimizer.step()

        loss_dict = {
            'content': content_loss.item(),
            'tv': tv_loss.item(),
            'color_generation': color_generation_loss.item(),
            'texture_generation': texture_generation_loss.item(),
            'color_discriminator': color_discriminator_loss.item(),
            'texture_discriminator': texture_discriminator_loss.item(),
        }
        return loss_dict

    def save_model(self, model_path):
        torch.save(self.generator_f.state_dict(), model_path + '_generator_f.pth')
        torch.save(self.generator_g.state_dict(), model_path + '_generator_g.pth')
        torch.save(self.discriminator_t.state_dict(), model_path + '_discriminator_t.pth')
        torch.save(self.discriminator_c.state_dict(), model_path + '_discriminator_c.pth')
